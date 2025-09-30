from django.core.management.base import BaseCommand
from django.utils import timezone
from django.core.mail import send_mail
from pos.models import Branch, Sale
from django.conf import settings

class Command(BaseCommand):
    help = "Send daily branch performance reports to Admin and Branch Managers (callable by cron)."

    def handle(self, *args, **options):
        today = timezone.localdate()
        branches = Branch.objects.all()
        admin_emails = [u.email for u in __import__("django.contrib.auth").contrib.auth.get_user_model().objects.filter(is_superuser=True, email__isnull=False)]
        for b in branches:
            sales = Sale.objects.filter(branch=b, created_at__date=today)
            total = sum(s.total for s in sales)
            count = sales.count()
            subject = f"Daily report for {b.name} - {today}"
            body = f"Branch: {b.name}\nDate: {today}\nTotal sales: {total}\nTransactions: {count}\n"
            # You can also add top products and expiry/low stock info here
            # Send to admin + branch manager emails: For demo, we send to superusers only
            recipients = admin_emails
            if recipients:
                send_mail(subject=subject, message=body, from_email=settings.DEFAULT_FROM_EMAIL, recipient_list=recipients, fail_silently=True)
        self.stdout.write("Daily reports processed.")
