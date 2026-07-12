def test_web_access_compatibility_module_delegates_to_web_handlers():
    from plugins.arteta_agent.tools import web_access
    from plugins.arteta_agent.tools.web import handlers

    assert web_access is handlers
    assert web_access.web_fetch is handlers.web_fetch
    assert web_access.web_search is handlers.web_search
    assert web_access.grok_search is handlers.grok_search
    assert web_access.fetch_x_post is handlers.fetch_x_post
    assert web_access.verify_recent_claim is handlers.verify_recent_claim
    assert web_access.register_tools is handlers.register_tools


def test_web_security_helpers_are_extracted_but_compatibly_exported():
    from plugins.arteta_agent.tools import web_access
    from plugins.arteta_agent.tools.web import handlers, security

    assert web_access._safe_url is security._safe_url
    assert handlers._safe_url is security._safe_url
    assert handlers._validate_public_http_url is security._validate_public_http_url
    assert handlers._has_sensitive_remote_query is security._has_sensitive_remote_query
    assert handlers._is_allowed_text_content_type is security._is_allowed_text_content_type
