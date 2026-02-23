from scripts import usage_calibration


def _role_summary(*, avg_g: float, avg_ip: float = 0.0) -> usage_calibration.RoleSummary:
    return usage_calibration.RoleSummary(count=1, g=avg_g, ip=avg_ip, gs=0.0)


def test_evaluate_role_targets_within_mlb_bands():
    summary = {
        "CL": _role_summary(avg_g=64.0, avg_ip=63.0),
        "SU": _role_summary(avg_g=62.0, avg_ip=61.0),
        "MR": _role_summary(avg_g=55.0, avg_ip=58.0),
        "LR": _role_summary(avg_g=42.0, avg_ip=70.0),
    }

    targets = usage_calibration.evaluate_role_targets(summary)

    assert targets["CL"]["all_in_range"] is True
    assert targets["SU"]["all_in_range"] is True
    assert targets["MR"]["all_in_range"] is True
    assert targets["LR"]["all_in_range"] is True


def test_evaluate_role_targets_flags_out_of_range_roles():
    summary = {
        "CL": _role_summary(avg_g=72.0, avg_ip=74.0),
        "SU": _role_summary(avg_g=58.0, avg_ip=59.0),
        "MR": _role_summary(avg_g=68.0, avg_ip=70.0),
        "LR": _role_summary(avg_g=30.0, avg_ip=60.0),
    }

    targets = usage_calibration.evaluate_role_targets(summary)

    assert targets["CL"]["all_in_range"] is False
    assert targets["SU"]["all_in_range"] is False
    assert targets["MR"]["all_in_range"] is False
    assert targets["LR"]["all_in_range"] is False
