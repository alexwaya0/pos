pharmacy_pos/
├─ manage.py
├─ requirements.txt
├─ README.md
├─ config/
│  ├─ __init__.py
│  ├─ asgi.py
│  ├─ settings.py
│  ├─ urls.py
│  └─ wsgi.py
├─ pos/
│  ├─ __init__.py
│  ├─ admin.py
│  ├─ apps.py
│  ├─ forms.py
│  ├─ management/
│  │  └─ commands/
│  │     └─ send_daily_reports.py
│  ├─ migrations/
│  │  └─ __init__.py
│  ├─ models.py
│  ├─ templates/
│  │  └─ pos/
│  │     ├─ base.html
│  │     ├─ sidebar.html
│  │     ├─ dashboard.html
│  │     ├─ product_list.html
│  │     ├─ product_add.html
│  │     ├─ sale_create.html
│  │     ├─ receipt.html
│  │     └─ reports.html
│  ├─ static/
│  │  └─ pos/
│  │     └─ js/
│  │        └─ notifications.js
│  ├─ tests.py
│  ├─ urls.py
│  └─ views.py
