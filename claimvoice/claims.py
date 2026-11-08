from copy import deepcopy

CLAIMS = {
    "SYN-AMB-1001": {"claim_id": "SYN-AMB-1001", "patient": "Fictional Patient A", "insurer": "Example Horizon Plan", "service_date": "2026-09-14", "service": "Synthetic emergency ambulance transport", "billed_amount": "1250.00", "original_status": "Submitted"},
    "SYN-AMB-1002": {"claim_id": "SYN-AMB-1002", "patient": "Fictional Patient B", "insurer": "Example Valley Plan", "service_date": "2026-09-18", "service": "Synthetic ambulance transport", "billed_amount": "980.00", "original_status": "Submitted"},
    "SYN-AMB-1003": {"claim_id": "SYN-AMB-1003", "patient": "Fictional Patient C", "insurer": "Example Summit Plan", "service_date": "2026-09-23", "service": "Synthetic ambulance transport", "billed_amount": "1450.00", "original_status": "Submitted"},
}
SCENARIOS = {
    "Pending processing": "Status: pending processing; Reference: DEMO-P17; Next action: check status again; Follow-up date: 2026-11-23",
    "Additional documents requested": "Status: additional documents requested; Reference: DEMO-D24; Documents: trip report, medical necessity statement; Next action: billing team to review document request",
    "Payment reported": "Status: payment reported; Reference: DEMO-R31; Next action: billing team to verify remittance",
}


def lookup(claim_id):
    if claim_id not in CLAIMS:
        raise ValueError("Unknown synthetic claim ID.")
    return deepcopy(CLAIMS[claim_id])
