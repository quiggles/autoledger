"""
tests/test_reminders.py
-----------------------
Tests for reminder CRUD, date/mileage status evaluation, and recurrence advance
on completion. Notification dispatch (HA/email) is exercised at the unit level
in test_notify.py; here channels are disabled so evaluation is pure.
"""

from datetime import date, timedelta

from routes.reminders import evaluate_reminder

# ── Pure status evaluation ─────────────────────────────────────────────────────

def test_date_reminder_due_within_lead_window():
    rem = {"label": "MOT", "type": "MOT",
           "due_date": (date.today() + timedelta(days=10)).isoformat(),
           "lead_days": 30}
    ev = evaluate_reminder(rem, current_mileage=None)
    assert ev["status"] == "due"
    assert ev["days_until"] == 10


def test_date_reminder_overdue():
    rem = {"label": "Tax", "type": "Tax",
           "due_date": (date.today() - timedelta(days=3)).isoformat(),
           "lead_days": 30}
    ev = evaluate_reminder(rem, current_mileage=None)
    assert ev["status"] == "overdue"


def test_date_reminder_ok_outside_window():
    rem = {"label": "Service", "type": "Service",
           "due_date": (date.today() + timedelta(days=200)).isoformat(),
           "lead_days": 30}
    ev = evaluate_reminder(rem, current_mileage=None)
    assert ev["status"] == "ok"


def test_mileage_reminder_due_within_lead():
    rem = {"label": "Service", "type": "Service",
           "due_mileage": 60000, "lead_miles": 500}
    ev = evaluate_reminder(rem, current_mileage=59700)
    assert ev["status"] == "due"
    assert ev["miles_until"] == 300


def test_mileage_reminder_overdue():
    rem = {"label": "Service", "type": "Service",
           "due_mileage": 60000, "lead_miles": 500}
    ev = evaluate_reminder(rem, current_mileage=60500)
    assert ev["status"] == "overdue"


def test_worst_of_date_and_mileage_wins():
    rem = {"label": "Service", "type": "Service",
           "due_date": (date.today() + timedelta(days=400)).isoformat(),  # ok
           "due_mileage": 60000, "lead_miles": 500, "lead_days": 30}
    ev = evaluate_reminder(rem, current_mileage=60500)  # mileage overdue
    assert ev["status"] == "overdue"


# ── CRUD + endpoints ───────────────────────────────────────────────────────────

def test_create_requires_date_or_mileage(client, vehicle):
    resp = client.post("/api/reminders", json={
        "vehicle_id": vehicle["id"], "type": "MOT",
    })
    assert resp.status_code == 400


def test_create_and_list_reminder(client, vehicle):
    resp = client.post("/api/reminders", json={
        "vehicle_id": vehicle["id"], "type": "MOT",
        "due_date": (date.today() + timedelta(days=5)).isoformat(),
    })
    assert resp.status_code == 201
    listed = client.get(f"/api/reminders?vehicle_id={vehicle['id']}").get_json()
    assert len(listed) == 1
    assert listed[0]["status"] == "due"


def test_due_endpoint_filters_to_due_and_overdue(client, vehicle):
    client.post("/api/reminders", json={
        "vehicle_id": vehicle["id"], "type": "MOT",
        "due_date": (date.today() + timedelta(days=5)).isoformat()})       # due
    client.post("/api/reminders", json={
        "vehicle_id": vehicle["id"], "type": "Service",
        "due_date": (date.today() + timedelta(days=300)).isoformat()})     # ok
    due = client.get("/api/reminders/due").get_json()
    assert len(due) == 1
    assert due[0]["type"] == "MOT"


def test_current_mileage_from_fuel_odometer(client, vehicle):
    client.post("/api/costs", json={
        "vehicle_id": vehicle["id"], "category": "Fuel", "amount": 50,
        "date": "2024-01-01", "odometer": 59800, "litres": 45, "is_full_tank": True})
    client.post("/api/reminders", json={
        "vehicle_id": vehicle["id"], "type": "Service",
        "due_mileage": 60000, "lead_miles": 500})
    rem = client.get(f"/api/reminders?vehicle_id={vehicle['id']}").get_json()[0]
    assert rem["current_mileage"] == 59800
    assert rem["status"] == "due"        # within 500 of 60000


def test_complete_advances_recurring_date(client, vehicle):
    created = client.post("/api/reminders", json={
        "vehicle_id": vehicle["id"], "type": "MOT",
        "due_date": (date.today() - timedelta(days=1)).isoformat(),  # overdue
        "recur_months": 12}).get_json()
    completed = client.post(f"/api/reminders/{created['id']}/complete").get_json()
    # New due date is ~12 months out from today, so it is no longer due.
    new_due = date.fromisoformat(completed["due_date"])
    assert new_due > date.today() + timedelta(days=300)
    assert completed["last_notified"] is None
