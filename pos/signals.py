from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver
from django.conf import settings
from .models import UserActivityLog

@receiver(user_logged_in)
def log_user_login(sender, request, user, **kwargs):
    """Log user login event with IP and user agent."""
    ip_address = request.META.get('REMOTE_ADDR', 'Unknown')
    user_agent = request.META.get('HTTP_USER_AGENT', 'Unknown')
    
    UserActivityLog.objects.create(
        user=user,
        action='login',
        ip_address=ip_address,
        user_agent=user_agent
    )

@receiver(user_logged_out)
def log_user_logout(sender, request, user, **kwargs):
    """Log user logout event with IP and user agent."""
    ip_address = request.META.get('REMOTE_ADDR', 'Unknown')
    user_agent = request.META.get('HTTP_USER_AGENT', 'Unknown')
    
    UserActivityLog.objects.create(
        user=user,
        action='logout',
        ip_address=ip_address,
        user_agent=user_agent
    )