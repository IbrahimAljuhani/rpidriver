"""
Tests for NeoLeap driver response parsers.

_parse_json_response — Format A (pure JSON from terminal, StatusCode "00"=approved)
_parse_xml_response  — Format B (hybrid JSON+XML from N950 production firmware)

No hardware or WebSocket required — pure function tests.
"""

import pytest

from rpidriver.plugins.neoleap_driver import NeoLeapDriver


# ── _parse_json_response ──────────────────────────────────────────────────────

class TestParseJsonResponse:

    def _make(self, status_code, **extra):
        """Build a Format-A data dict with the given StatusCode."""
        jr = {"StatusCode": status_code, **extra}
        return {"EventName": "TERMINAL_RESPONSE", "JsonResult": jr}

    def test_approved_sets_state_accepted(self):
        data = self._make(
            "00",
            ECRReferenceNumber="000001",
            TransactionAuthCode="AB1234",
            CardType="MADA",
            TerminalID="12345678",
        )
        result = NeoLeapDriver._parse_json_response(data)
        assert result["state"] == "accepted"

    def test_approved_extracts_rrn(self):
        data = self._make("00", ECRReferenceNumber="999888777666")
        result = NeoLeapDriver._parse_json_response(data)
        assert result["transactionId"] == "999888777666"

    def test_approved_extracts_auth_code(self):
        data = self._make("00", TransactionAuthCode="ZZ9999")
        result = NeoLeapDriver._parse_json_response(data)
        assert result["authCode"] == "ZZ9999"

    def test_approved_extracts_card_type(self):
        data = self._make("00", CardType="VISA")
        result = NeoLeapDriver._parse_json_response(data)
        assert result["cardType"] == "VISA"

    def test_approved_status_code_00(self):
        data = self._make("00")
        result = NeoLeapDriver._parse_json_response(data)
        assert result["statusCode"] == "00"

    def test_declined_sets_state_error(self):
        data = self._make("01")
        result = NeoLeapDriver._parse_json_response(data)
        assert result["state"] == "error"

    def test_cancelled_sets_state_cancelled(self):
        data = self._make("11")
        result = NeoLeapDriver._parse_json_response(data)
        assert result["state"] == "cancelled"

    def test_unknown_status_code_sets_state_error(self):
        data = self._make("99")
        result = NeoLeapDriver._parse_json_response(data)
        assert result["state"] == "error"

    def test_missing_json_result_does_not_crash(self):
        result = NeoLeapDriver._parse_json_response({"EventName": "TERMINAL_RESPONSE"})
        assert "state" in result

    def test_empty_dict_does_not_crash(self):
        result = NeoLeapDriver._parse_json_response({})
        assert "state" in result


# ── _parse_xml_response ───────────────────────────────────────────────────────

# Real-world N950 Format B hybrid message structure (ResponseCode uses 3 digits)
_FORMAT_B_APPROVED = (
    '{"API_Status":"0","EventName":"TERMINAL_RESPONSE",'
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<madaTransactionResult>'
    '<Result Language="AR" English="APPROVED" Arabic="موافق"/>'
    '<ResponseCode>000</ResponseCode>'
    '<ApprovalCode>AB5678</ApprovalCode>'
    '<RRN>987654321098</RRN>'
    '<TerminalID>12345678</TerminalID>'
    '<CardType>MADA</CardType>'
    '</madaTransactionResult>'
)

_FORMAT_B_DECLINED = (
    '{"API_Status":"0","EventName":"TERMINAL_RESPONSE",'
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<madaTransactionResult>'
    '<Result Language="AR" English="DECLINED" Arabic="مرفوض"/>'
    '<ResponseCode>051</ResponseCode>'
    '<ApprovalCode></ApprovalCode>'
    '<RRN></RRN>'
    '<TerminalID>12345678</TerminalID>'
    '<CardType>MADA</CardType>'
    '</madaTransactionResult>'
)

_FORMAT_B_CANCELLED = (
    '{"API_Status":"0","EventName":"TERMINAL_RESPONSE",'
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<madaTransactionResult>'
    '<Result Language="AR" English="CANCELLED" Arabic="ملغي"/>'
    '<ResponseCode>099</ResponseCode>'
    '<RRN></RRN>'
    '<TerminalID>12345678</TerminalID>'
    '</madaTransactionResult>'
)


class TestParseXmlResponse:

    def test_approved_sets_state_accepted(self):
        result = NeoLeapDriver._parse_xml_response(_FORMAT_B_APPROVED)
        assert result["state"] == "accepted"

    def test_approved_extracts_rrn(self):
        result = NeoLeapDriver._parse_xml_response(_FORMAT_B_APPROVED)
        assert result["transactionId"] == "987654321098"

    def test_approved_extracts_approval_code(self):
        result = NeoLeapDriver._parse_xml_response(_FORMAT_B_APPROVED)
        assert result["authCode"] == "AB5678"

    def test_approved_extracts_card_type(self):
        result = NeoLeapDriver._parse_xml_response(_FORMAT_B_APPROVED)
        assert result["cardType"] == "MADA"

    def test_approved_extracts_terminal_id(self):
        result = NeoLeapDriver._parse_xml_response(_FORMAT_B_APPROVED)
        assert result["terminalId"] == "12345678"

    def test_approved_response_code_000(self):
        result = NeoLeapDriver._parse_xml_response(_FORMAT_B_APPROVED)
        assert result["statusCode"] == "000"

    def test_declined_sets_state_error(self):
        result = NeoLeapDriver._parse_xml_response(_FORMAT_B_DECLINED)
        assert result["state"] == "error"

    def test_declined_has_status_code(self):
        result = NeoLeapDriver._parse_xml_response(_FORMAT_B_DECLINED)
        assert result["statusCode"] == "051"

    def test_cancelled_sets_state_error_or_cancelled(self):
        # CANCELLED is not "APPROVED" so it maps to error in the XML parser
        result = NeoLeapDriver._parse_xml_response(_FORMAT_B_CANCELLED)
        assert result["state"] in ("error", "cancelled")

    def test_approved_via_response_code_only(self):
        """If Result attribute is missing, ResponseCode 000 must still approve."""
        xml = (
            '<?xml version="1.0"?><madaTransactionResult>'
            '<ResponseCode>000</ResponseCode>'
            '<ApprovalCode>XY1234</ApprovalCode>'
            '<RRN>111222333444</RRN>'
            '</madaTransactionResult>'
        )
        result = NeoLeapDriver._parse_xml_response(xml)
        assert result["state"] == "accepted"

    def test_garbage_input_does_not_crash(self):
        result = NeoLeapDriver._parse_xml_response("NOT_XML_OR_JSON_AT_ALL")
        assert "state" in result

    def test_empty_string_does_not_crash(self):
        result = NeoLeapDriver._parse_xml_response("")
        assert "state" in result
