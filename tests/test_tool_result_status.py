from codess.tool_result_status import application_failure_evidence


def test_nested_json_error_is_detected():
    value = '{"result":"{\\"content\\":[{\\"text\\":\\"Failed to move root\\"}]}"}'
    assert "Failed to move root" in application_failure_evidence(value)


def test_output_wrapped_error_object_is_detected():
    value = 'Wall time: 0.2 seconds\nOutput:\n{"error":"API rejected query"}'
    assert application_failure_evidence(value) == "$.json.error"


def test_arbitrary_success_prose_is_not_scanned_for_error_words():
    value = {"issues": [{"body": "Error handling was improved."}]}
    assert application_failure_evidence(value) is None
