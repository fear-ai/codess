from codess.mcp_audit import _discovery_details, classify_mcp_invocation


def test_discovery_target_error_is_separate_from_discovery_operation():
    classification, likely_use = classify_mcp_invocation(
        "get_mcp_tools",
        source_status="completed",
        normalized_status="succeeded",
        result='{"serverStatus":"error","tools":[{"name":"mcp_auth"}]}',
    )
    assert classification == "discovery_target_error"
    assert likely_use == "tool/resource discovery"


def test_admin_result_failure_is_not_admin_success():
    classification, _ = classify_mcp_invocation(
        "mcp-cursor-app-control-move_agent_to_root",
        source_status="completed",
        normalized_status="succeeded",
        result='{"result":"Failed to move agent root"}',
    )
    assert classification == "operation_failure"


def test_visualization_result_is_classified_by_use():
    classification, _ = classify_mcp_invocation(
        "mcp__visualize__show_widget",
        source_status="completed",
        normalized_status="succeeded",
        result="Content rendered and shown to the user",
    )
    assert classification == "visualization_success"


def test_discovery_details_unwrap_nested_json():
    value = (
        '{"content":"{\\"server\\":\\"user-brave-search\\",'
        '\\"serverStatus\\":\\"error\\",'
        '\\"tools\\":[{\\"name\\":\\"mcp_auth\\"}]}"}'
    )
    assert _discovery_details(value) == {
        "target_server": "user-brave-search",
        "target_server_status": "error",
        "discovered_tool_names": ["mcp_auth"],
    }
