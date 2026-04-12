"""
Tests for _format_receipt() in escpos_driver.py.

No hardware or USB required — tests the receipt formatting logic only.
"""

from rpidriver.plugins.escpos_driver import _format_receipt


MINIMAL_RECEIPT = {
    "company": {"name": "Test Shop"},
    "name": "POS/001",
    "orderlines": [
        {"product_name": "Coffee", "qty": 2, "price_display": "5.00"},
    ],
    "total_with_tax": 10.0,
    "amount_paid": 10.0,
}


def test_returns_list_of_strings():
    lines = _format_receipt(MINIMAL_RECEIPT)
    assert isinstance(lines, list)
    assert all(isinstance(l, str) for l in lines)


def test_company_name_present():
    lines = _format_receipt(MINIMAL_RECEIPT)
    assert any("Test Shop" in l for l in lines)


def test_order_name_present():
    lines = _format_receipt(MINIMAL_RECEIPT)
    assert any("POS/001" in l for l in lines)


def test_product_name_present():
    lines = _format_receipt(MINIMAL_RECEIPT)
    assert any("Coffee" in l for l in lines)


def test_total_present():
    lines = _format_receipt(MINIMAL_RECEIPT)
    assert any("10.00" in l for l in lines)


def test_default_thank_you_message():
    lines = _format_receipt(MINIMAL_RECEIPT)
    assert any("Thank you" in l for l in lines)


def test_custom_thank_you_message():
    lines = _format_receipt(MINIMAL_RECEIPT, thank_you="Goodbye!")
    assert any("Goodbye!" in l for l in lines)
    assert not any("Thank you" in l for l in lines)


def test_cols_respected():
    lines = _format_receipt(MINIMAL_RECEIPT, cols=32)
    # No line should exceed cols characters (separators are exactly cols wide)
    for l in lines:
        assert len(l) <= 32, f"Line too long ({len(l)}): {l!r}"


def test_empty_orderlines():
    receipt = {**MINIMAL_RECEIPT, "orderlines": []}
    lines = _format_receipt(receipt)
    assert isinstance(lines, list)
    assert len(lines) > 0


def test_paymentlines_rendered():
    receipt = {
        **MINIMAL_RECEIPT,
        "paymentlines": [{"name": "Cash", "amount": 10.0}],
    }
    lines = _format_receipt(receipt)
    assert any("Cash" in l for l in lines)


def test_change_rendered():
    receipt = {**MINIMAL_RECEIPT, "amount_paid": 20.0, "amount_return": 10.0}
    lines = _format_receipt(receipt)
    assert any("Change" in l for l in lines)


def test_vat_fields():
    receipt = {
        **MINIMAL_RECEIPT,
        "company": {"name": "Test", "vat": "SA123456"},
    }
    lines = _format_receipt(receipt)
    assert any("SA123456" in l for l in lines)
