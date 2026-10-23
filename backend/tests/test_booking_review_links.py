"""A review item must preserve the exact booking identity in its navigation URL."""

from datetime import date

from backend.models import Booking
from backend.services.review import review_items
from backend.storage import InMemoryStore


def test_review_link_encodes_imported_booking_id_without_changing_it():
    store = InMemoryStore()
    booking = Booking(id="bank +?#ä", account_id="account", booking_date=date(2026, 9, 3), amount=612)
    store.bookings[booking.id] = booking

    items = review_items(store, date(2026, 10, 7))

    assert len(items) == 1
    assert items[0]["entity_id"] == "bank +?#ä"
    assert items[0]["link"] == "/bookings?booking_id=bank%20%2B%3F%23%C3%A4"
