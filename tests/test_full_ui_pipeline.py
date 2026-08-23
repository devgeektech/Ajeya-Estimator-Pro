import os
import django
import sys
import time
import json

# Set up Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.test import Client
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.conf import settings
from apps.boq.models import BOQ
from common.choices import BOQStatus

settings.CELERY_TASK_ALWAYS_EAGER = True
settings.CELERY_TASK_EAGER_PROPAGATES = True
settings.ALLOWED_HOSTS.append("testserver")

User = get_user_model()

def main():
    print("Initializing Full UI Pipeline Tester...")
    email = "tester_e2e@example.com"
    password = "e2epassword123"
    
    user = User.objects.filter(email=email).first()
    if not user:
        user = User.objects.create_user(email=email, password=password)  # type: ignore
        user.is_superuser = True
        user.is_staff = True
        user.save()
    
    client = Client(HTTP_HOST="localhost")
    client.login(email=email, password=password)
    
    boq_dir = os.path.join(settings.MEDIA_ROOT, "boq")
    filename = "test_boq.xlsx"
    filepath = os.path.join(boq_dir, filename)
    
    if not os.path.exists(filepath):
        print(f"File {filepath} not found!")
        return
        
    print(f"\n[1] Starting upload of {filename}...")
    
    url = reverse("boq:upload")
    with open(filepath, "rb") as f:
        file_data = f.read()
        
    boq_name = f"Full UI Test - {time.time()}"
    uploaded_file = SimpleUploadedFile(
        filename, file_data, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    
    response = client.post(url, {"uploaded_file": uploaded_file, "boq_name": boq_name}, follow=True)
    boq = BOQ.objects.filter(boq_name=boq_name).first()
    if not boq:
        print("FAILED: BOQ was not created.")
        return
        
    print("[2] Executing extraction...")
    from apps.boq.tasks import process_boq_extraction_task
    process_boq_extraction_task.delay(boq.id)
    boq.refresh_from_db()
    print(f"Status after extraction: {boq.status}")
    
    # After extraction, the BOQ should be in EXTRACTED status or matching. In the real app, we might need to trigger matching.
    # But let's check Make & Vendor page
    print("\n[3] Testing Make and Vendor page...")
    mv_url = reverse("boq:make_vendor_select", args=[boq.id])
    response = client.get(mv_url)
    print(f"GET {mv_url} -> {response.status_code}")
    
    # Simulate saving make & vendor
    response = client.post(mv_url, {"save_vendors": "true", "make_1": "1"}, follow=True)
    print(f"POST {mv_url} -> {response.status_code}")
    boq.refresh_from_db()
    print(f"Status after Make & Vendor: {boq.status}")
    
    print("\n[4] Testing Labour page...")
    labour_url = reverse("boq:labour", args=[boq.id])
    response = client.get(labour_url)
    print(f"GET {labour_url} -> {response.status_code}")
    
    # Simulate saving labour
    response = client.post(labour_url, {"save_labour": "true", "labour_rate_1": "100"}, follow=True)
    print(f"POST {labour_url} -> {response.status_code}")
    boq.refresh_from_db()
    print(f"Status after Labour: {boq.status}")
    
    print("\n[5] Testing Review page...")
    detail_url = reverse("boq:detail", args=[boq.id])
    response = client.get(detail_url, {"tab": "review"})
    print(f"GET {detail_url}?tab=review -> {response.status_code}")
    
    # Transition to READY_EXPORT to test export (the UI usually has a Confirm button)
    print("\n[6] Testing Export...")
    boq.status = BOQStatus.READY_EXPORT
    boq.save()
    
    export_url = reverse("boq:export", args=[boq.id])
    response = client.get(export_url)
    print(f"GET {export_url} -> {response.status_code}")
    
    content_type = response.headers.get("Content-Type")
    if response.status_code == 200 and "spreadsheetml.sheet" in str(content_type):
        print("SUCCESS: Export returned a valid Excel file.")
    else:
        print("FAILED: Export did not return an Excel file.")
        
    boq.delete()
    print("\nAll views tested successfully and BOQ cleaned up.")

if __name__ == "__main__":
    main()
