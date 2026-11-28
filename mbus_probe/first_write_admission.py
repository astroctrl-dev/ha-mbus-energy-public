"""First-write beta admission policy; no physical transport is installed here."""
from address_policy import validate_address


class FirstWriteAdmission:
    """Fail closed unless explicitly enabled and independently qualified.

    Qualification must be supplied by a verified runtime evidence provider,
    never by a browser flag or by the discovery result itself.
    """
    def __init__(self, enabled=False, qualification=None):
        self.enabled = enabled is True
        self.qualification = qualification

    def require(self, meter_id, old_address, new_address, *, confirmed=False,
                override=False, accepted_risk=None):
        validate_address(old_address)
        validate_address(new_address)
        if not self.enabled:
            raise ValueError("physical address writing disabled")
        if (confirmed is not True or override is not False or accepted_risk is not None
                or not isinstance(meter_id, str) or old_address == new_address):
            raise ValueError("only explicitly confirmed non-conflicting changes allowed")
        if not callable(self.qualification) or self.qualification(meter_id, old_address) is not True:
            raise ValueError("independent physical qualification required")
