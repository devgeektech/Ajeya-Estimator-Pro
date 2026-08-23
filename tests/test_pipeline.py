import os
import django
import sys
import time

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

# Force celery to execute synchronously for testing
settings.CELERY_TASK_ALWAYS_EAGER = True
settings.CELERY_TASK_EAGER_PROPAGATES = True

User = get_user_model()

def main():
    print("Initializing E2E Pipeline Tester...")
    # Create test user
    email = "tester_e2e@example.com"
    password = "e2epassword123"
    
    user = User.objects.filter(email=email).first()
    if not user:
        user = User.objects.create_user(email=email, password=password)  # type: ignore
        user.is_superuser = True
        user.is_staff = True
        user.save()
    
    settings.ALLOWED_HOSTS.append("testserver")
    client = Client(HTTP_HOST="localhost")
    client.login(email=email, password=password)
    
    boq_dir = os.path.join(settings.MEDIA_ROOT, "boq")
    
    if not os.path.exists(boq_dir):
        print(f"Directory {boq_dir} does not exist.")
        return
        
    boq_files = [f for f in os.listdir(boq_dir) if f.endswith(".xlsx") and not f.startswith("~$")]
    
    print(f"Found {len(boq_files)} BOQs to test.")
    
    for filename in boq_files:
        filepath = os.path.join(boq_dir, filename)
        print(f"\n[{filename}] Starting test...")
        
        url = reverse("boq:upload")
        with open(filepath, "rb") as f:
            file_data = f.read()
            
        boq_name = f"E2E Test - {filename} - {time.time()}"
        
        uploaded_file = SimpleUploadedFile(
            filename,
            file_data,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        
        # Simulate upload (which triggers validation and extraction since Celery is eager)
        print(f"[{filename}] Uploading...")
        response = client.post(url, {"uploaded_file": uploaded_file, "boq_name": boq_name}, follow=True)
        
        # Verify
        boq = BOQ.objects.filter(boq_name=boq_name).first()
        if not boq:
            print(f"[{filename}] FAILED: BOQ was not created.")
            continue
            
        print(f"[{filename}] Uploaded. Executing extraction...")
        from apps.boq.tasks import process_boq_extraction_task
        process_boq_extraction_task.delay(boq.id)
        
        boq.refresh_from_db()
            
        if boq.status == BOQStatus.ANALYSIS_FAILED:
            print(f"[{filename}] FAILED: BOQ upload/extraction failed. (Upload failed status)")
            print(f"Analysis Data: {boq.analysis_data}")
            continue
            
        print(f"[{filename}] Extraction completed. Status: {boq.status}")
        
        # Validate output
        analysis = boq.analysis_data or {}
        lines = analysis.get("lines", [])
        print(f"[{filename}] Found {len(lines)} extracted lines.")
        
        job_only_count = 0
        product_violations = 0
        total_products = 0
        
        for line in lines:
            if line.get("is_activity_only"):
                job_only_count += 1
                
            qty = line.get("qty")
            products = line.get("products", [])
            total_products += len(products)

        print(f"[{filename}] Job-only rows identified: {job_only_count}")
        print(f"[{filename}] Total products extracted: {total_products}")
        
        # Clean up
        boq.delete()
        print(f"[{filename}] Cleaned up BOQ.")

if __name__ == "__main__":
    main()
