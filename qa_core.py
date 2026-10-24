"""Core helpers for the AI QA Engineering Agent demo.

The template mode is deterministic and does not call an LLM. AI mode is optional.
Never send production secrets or proprietary data to an external model.
"""
from __future__ import annotations

import csv
import io
import json
import re
import shlex
import zipfile
from urllib.parse import parse_qsl, urlencode, urlsplit
from typing import Any


SUPPORTED_GUIDANCE_EXTENSIONS = {".md", ".markdown", ".txt"}
MAX_GUIDANCE_FILE_CHARS = 40_000


def decode_guidance_file(filename: str, raw_bytes: bytes, max_chars: int = MAX_GUIDANCE_FILE_CHARS) -> tuple[str, bool]:
    """Decode a small Markdown/text guidance file for use as project context.

    Returns (content, was_truncated). Only plain-text extensions are accepted.
    Uploaded content should be treated as untrusted input and reviewed before use.
    """
    from pathlib import PurePath

    suffix = PurePath(filename).suffix.lower()
    if suffix not in SUPPORTED_GUIDANCE_EXTENSIONS:
        allowed = ", ".join(sorted(SUPPORTED_GUIDANCE_EXTENSIONS))
        raise ValueError(f"Unsupported guidance file type '{suffix or '(none)'}'. Use: {allowed}.")
    if max_chars < 1:
        raise ValueError("max_chars must be greater than zero.")
    content = raw_bytes.decode("utf-8-sig", errors="replace")
    truncated = len(content) > max_chars
    return content[:max_chars], truncated


def build_template_test_cases(requirements: str, context: str = "") -> list[dict[str, str]]:
    """Return a generic baseline test suite; review and tailor it before use."""
    text = f"{requirements}\n{context}".lower()
    subject = "the requested feature"
    for keyword, label in [
        ("login", "login"), ("order", "order creation"), ("payment", "payment"),
        ("user", "user management"), ("upload", "file upload"),
        ("search", "search"), ("booking", "booking"), ("password", "password reset"),
    ]:
        if keyword in text:
            subject = label
            break

    cases = [
        ("TC-001", "Positive", f"Verify successful {subject} with valid inputs", "Provide valid required data and submit the request/action.", "The operation succeeds and the response/UI shows the expected business outcome.", "High"),
        ("TC-002", "Negative", f"Verify {subject} when a required field is missing", "Omit one required field and submit.", "A clear validation error is returned; no unintended state change occurs.", "High"),
        ("TC-003", "Negative", f"Verify {subject} with invalidly formatted data", "Provide malformed data for a field with a format constraint.", "The input is rejected with an appropriate validation message/status.", "High"),
        ("TC-004", "Boundary", f"Verify minimum and maximum boundaries for {subject}", "Test values just below, at, and just above each documented boundary.", "Only values within the documented constraints are accepted.", "High"),
        ("TC-005", "Authorization", f"Verify {subject} without authentication", "Repeat the request/action without a valid session/token.", "Access is denied (for example, HTTP 401 for an API); protected data is not exposed.", "High"),
        ("TC-006", "Authorization", f"Verify {subject} with insufficient permissions", "Use an authenticated user lacking the required permission.", "Access is denied (for example, HTTP 403 for an API) and no unauthorized change occurs.", "High"),
        ("TC-007", "Resilience", f"Verify {subject} when a dependent service is unavailable", "Simulate a dependency timeout or service error in a safe test environment.", "Failure is handled gracefully, is observable in logs, and does not leave partial invalid data.", "Medium"),
        ("TC-008", "Regression", f"Verify existing related flows after {subject}", "Execute the key related workflows and inspect persisted state.", "Existing supported behavior remains unchanged and data is consistent.", "High"),
        ("TC-009", "Duplicate", f"Verify repeated submission of {subject}", "Submit the same request/action twice, including a quick repeat.", "The outcome follows the documented duplicate/idempotency rule; no accidental duplicate is created.", "Medium"),
        ("TC-010", "Data integrity", f"Verify data consistency after {subject}", "Complete the operation, then retrieve the resulting record through the supported read path.", "Persisted values, response values, and related records are consistent.", "High"),
    ]
    return [dict(zip(("id", "type", "title", "steps", "expected", "priority"), row)) for row in cases]


def cases_to_csv(cases: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    fields = ["id", "type", "title", "steps", "expected", "priority"]
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for case in cases:
        writer.writerow({field: case.get(field, "") for field in fields})
    return buf.getvalue()


def redact_curl(curl: str) -> str:
    """Best-effort redaction before displaying/passing cURL text to an LLM."""
    text = curl.replace("\\\r\n", " ").replace("\\\n", " ")
    # Redact common secrets in header values and query parameters.
    # Preserve the Bearer scheme so the code generator can map it to API_TOKEN.
    # Redact user-info embedded in a URL (for example https://user:pass@host/path).
    text = re.sub(r"(?i)(https?://)[^/@\s:]+:[^/@\s]+@", r"\1REDACTED@", text)
    # Keep the Bearer scheme as a useful hint but never preserve the credential value.
    text = re.sub(
        r"(?i)(authorization\s*:\s*)Bearer\s+[^'\"\n]+",
        r"\1Bearer [REDACTED]", text,
    )
    # Other auth-bearing headers are fully masked, including Basic Authorization.
    text = re.sub(
        r"(?i)((?:[A-Za-z0-9_-]*(?:authorization|auth|api[_-]?key|apikey|token|cookie|session|secret)[A-Za-z0-9_-]*)\s*:\s*)(?!\s*Bearer \[REDACTED\])([^'\"\n]+)",
        r"\1[REDACTED]", text,
    )
    # Mask Basic-auth credentials provided with curl -u/--user before any optional AI call.
    text = re.sub(r"(?i)(-u|--user)\s+(\"[^\"]*\"|'[^']*'|\S+)", r"\1 ${API_USERNAME}:${API_PASSWORD}", text)
    text = re.sub(r"(?i)([?&](?:access[_-]?token|refresh[_-]?token|auth(?:orization)?|api[_-]?key|apikey|token|password|client[_-]?secret|secret|session[_-]?id|cookie|signature|jwt|credential)=)[^&\s'\"]+", r"\1[REDACTED]", text)
    # Basic JSON secret masking for common payload fields; still avoid sending sensitive payloads.
    text = re.sub(
        r'(?i)("(?:password|secret|client_secret|access_token|refresh_token|api[_-]?key|apikey|token|authorization|cookie)"\s*:\s*)"[^"]*"',
        r'\1"[REDACTED]"', text,
    )
    return text


def parse_curl(curl: str) -> dict[str, Any]:
    """Parse common curl flags needed for the demo; not a complete curl parser."""
    clean = curl.replace("\\\r\n", " ").replace("\\\n", " ").strip()
    # Remove leading `curl` and parse shell-like quoting.
    try:
        tokens = shlex.split(clean, posix=True)
    except ValueError as exc:
        raise ValueError(f"Could not parse cURL quoting: {exc}") from exc
    if tokens and tokens[0].lower() == "curl":
        tokens = tokens[1:]
    method = "GET"
    url = ""
    headers: dict[str, str] = {}
    body = None
    basic_auth = False
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in ("-X", "--request") and i + 1 < len(tokens):
            method = tokens[i + 1].upper(); i += 2; continue
        if tok in ("-H", "--header") and i + 1 < len(tokens):
            header = tokens[i + 1]
            if ":" in header:
                key, value = header.split(":", 1)
                headers[key.strip()] = value.strip()
            i += 2; continue
        if tok in ("-d", "--data", "--data-raw", "--data-binary", "--data-urlencode") and i + 1 < len(tokens):
            body = tokens[i + 1]
            if method == "GET":
                method = "POST"
            i += 2; continue
        if tok in ("-u", "--user") and i + 1 < len(tokens):
            # Never retain cURL basic-auth credentials; generated tests read env vars instead.
            basic_auth = True
            i += 2; continue
        if tok in ("-I", "--head"):
            method = "HEAD"; i += 1; continue
        if tok.startswith("-"):
            i += 1; continue
        if tok.startswith(("http://", "https://")):
            url = tok
        i += 1

    if not url:
        raise ValueError("Could not find an http:// or https:// URL in the cURL command.")

    # Mask sensitive header values in the parsed output.
    safe_headers = {}
    for key, value in headers.items():
        if re.search(r"(?i)(authorization|auth|api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|cookie|session|secret)", key):
            if key.lower() == "authorization" and value.lower().startswith("bearer "):
                safe_headers[key] = "Bearer ${API_TOKEN}"
            else:
                safe_headers[key] = "${" + re.sub(r"[^A-Za-z0-9]", "_", key.upper()) + "}"
        else:
            safe_headers[key] = value
    # Redact credentials embedded in query string for demo safety.
    url = re.sub(r"(?i)([?&](?:access_token|api_key|apikey|token|password)=)[^&]+", r"\1${REDACTED}", url)
    return {"method": method, "url": url, "headers": safe_headers, "body": body, "basic_auth": basic_auth}


def java_string(value: str) -> str:
    """Escape value for a Java string literal."""
    return json.dumps(value, ensure_ascii=False)


def build_restassured_template(curl: str) -> str:
    parsed = parse_curl(curl)
    url = parsed["url"]
    method = parsed["method"]
    headers = parsed["headers"]
    body = parsed["body"]

    lines = [
        "import io.restassured.http.ContentType;",
        "import org.testng.annotations.Test;",
        "import static io.restassured.RestAssured.given;",
        "import static org.hamcrest.Matchers.*;",
        "",
        "/**",
        " * Generated starter test. Review endpoint, secrets, and assertions against the API contract.",
        " * Expected status 200 is a placeholder; change it to the documented response (e.g. 201).",
        " */",
        "public class GeneratedApiTest {",
        "    @Test",
        "    public void generated_api_test() {",
        "        given()",
    ]
    for key, value in headers.items():
        if key.lower() == "authorization" and "${API_TOKEN}" in value:
            lines.append('            .header("Authorization", "Bearer " + System.getenv("API_TOKEN"))')
        elif value.startswith("${") and value.endswith("}"):
            env_name = value[2:-1]
            lines.append(f'            .header({java_string(key)}, System.getenv({java_string(env_name)}))')
        else:
            lines.append(f'            .header({java_string(key)}, {java_string(value)})')
    if body is not None:
        lines.append(f"            .body({java_string(body)})")
    lines += [
        f"        .when()",
        f"            .request({java_string(method)}, {java_string(url)})",
        "        .then()",
        "            .statusCode(200); // TODO: assert documented status and business response",
        "    }",
        "}",
    ]
    return "\n".join(lines)


def classify_failure(stacktrace: str, code: str = "") -> dict[str, str]:
    text = f"{stacktrace}\n{code}".lower()
    if any(x in text for x in ("no such element", "nosuchelement", "strict mode violation", "locator")):
        return {"category": "Likely locator / UI synchronization issue", "analysis": "Check whether the element locator changed, whether the page state is correct, and whether the test waits for a meaningful condition.", "action": "Compare DOM/accessibility evidence, prefer stable role/test-id locators, and add an explicit state-based wait only if justified.", "safety": "Do not weaken business assertions or add arbitrary sleeps as the first response."}
    if any(x in text for x in ("401", "unauthorized", "token expired", "invalid token")):
        return {"category": "Authentication / token issue", "analysis": "The test may be using an expired or incorrectly configured credential, or the service may have changed its auth behavior.", "action": "Verify secret injection, token expiry, scopes, and environment configuration in the approved test environment.", "safety": "Do not bypass authentication or commit secrets into code."}
    if any(x in text for x in ("500", "internal server error", "502", "503", "504")):
        return {"category": "Possible service / environment failure", "analysis": "A server-side or dependency failure may be the cause; a test rewrite could hide a real product defect.", "action": "Correlate timestamps/request IDs with service logs, retry only under a defined policy, and raise a defect if reproducible.", "safety": "Do not label the test as healed until the service behavior and expected contract are verified."}
    if any(x in text for x in ("assertionerror", "expected:", "actual:", "assertion failed")):
        return {"category": "Assertion / behavior mismatch", "analysis": "The observed result differs from the expected result. This could be a product regression, stale test data, or an incorrect expectation.", "action": "Verify the acceptance criteria and API/UI contract, inspect response evidence and test data, then update the assertion only when requirements justify it.", "safety": "Never auto-change an assertion merely to make the test pass."}
    if any(x in text for x in ("timeout", "timed out", "connection refused", "dns")):
        return {"category": "Timeout / connectivity / environment", "analysis": "The test may be racing a slow operation or the target environment/service may be unhealthy.", "action": "Check service health and logs, distinguish product latency from test synchronization, and use bounded retries only for documented transient operations.", "safety": "Avoid arbitrary long sleeps and avoid masking persistent instability with retries."}
    return {"category": "Unclassified failure — investigation required", "analysis": "The provided evidence is insufficient for a confident diagnosis.", "action": "Collect full stack trace, test name, environment/build, request/response or DOM evidence, recent changes, and a reproducible example.", "safety": "Do not apply an automatic code change until the failure is classified and evidence supports the fix."}


JAVA_KEYWORDS = {
    "abstract", "assert", "boolean", "break", "byte", "case", "catch", "char", "class", "const",
    "continue", "default", "do", "double", "else", "enum", "extends", "final", "finally", "float",
    "for", "goto", "if", "implements", "import", "instanceof", "int", "interface", "long", "native",
    "new", "package", "private", "protected", "public", "return", "short", "static", "strictfp", "super",
    "switch", "synchronized", "this", "throw", "throws", "transient", "try", "void", "volatile", "while",
    "true", "false", "null", "record", "var", "yield", "sealed", "permits",
}


def _safe_class_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_$]", "", value.strip())
    if not cleaned:
        cleaned = "GeneratedApiTest"
    if not (cleaned[0].isalpha() or cleaned[0] in "_$"):
        cleaned = "Generated" + cleaned
    if cleaned in JAVA_KEYWORDS:
        cleaned += "Test"
    return cleaned


def _safe_package_name(value: str) -> str:
    parts = value.strip().split(".") if value.strip() else ["com", "example", "qa"]
    valid_parts = []
    for part in parts:
        cleaned = re.sub(r"[^A-Za-z0-9_$]", "", part)
        if cleaned != part or not cleaned or not (cleaned[0].isalpha() or cleaned[0] in "_$") or cleaned in JAVA_KEYWORDS:
            raise ValueError(f"Invalid Java package component: {part!r}")
        valid_parts.append(cleaned)
    return ".".join(valid_parts)


def _java_literal(value: str) -> str:
    """Return a correctly escaped Java string literal for text values."""
    return json.dumps(value, ensure_ascii=False)


def _body_without_field(body: str, field_name: str) -> str | None:
    """Remove one top-level JSON object property, returning compact JSON or None."""
    try:
        payload = json.loads(body)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or field_name not in payload:
        return None
    payload.pop(field_name)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _top_level_json_fields(body: str | None) -> list[str]:
    if not body:
        return []
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return []
    return [str(k) for k in payload.keys()] if isinstance(payload, dict) else []


def _replace_sensitive_body_values(payload: Any, env_names: set[str]) -> Any:
    """Replace sensitive string values in JSON payloads with runtime env placeholders."""
    sensitive_name = re.compile(r"(?i)(password|secret|client_secret|access_token|refresh_token|api[_-]?key|apikey|token|authorization|cookie)")
    if isinstance(payload, dict):
        transformed = {}
        for key, value in payload.items():
            if sensitive_name.search(str(key)) and isinstance(value, str):
                env_name = re.sub(r"[^A-Za-z0-9]", "_", str(key)).upper() or "BODY_SECRET"
                env_names.add(env_name)
                transformed[key] = f"__ENV_{env_name}__"
            else:
                transformed[key] = _replace_sensitive_body_values(value, env_names)
        return transformed
    if isinstance(payload, list):
        return [_replace_sensitive_body_values(item, env_names) for item in payload]
    return payload


def build_restassured_project(
    curl: str,
    *,
    class_name: str = "GeneratedApiTest",
    package_name: str = "com.example.qa",
    expected_success_status: int = 201,
    expected_bad_request_status: int = 400,
    expected_unauthorized_status: int = 401,
    required_fields: list[str] | None = None,
    response_paths: list[str] | None = None,
    include_missing_auth: bool = True,
    include_malformed_json: bool = True,
) -> dict[str, str]:
    """Build a reusable Maven + RestAssured + TestNG project from a cURL request.

    The output is a guarded integration-test starter, not a guarantee of business correctness.
    Confirm the true API contract before running it against a test environment.
    """
    if not 100 <= int(expected_success_status) <= 599:
        raise ValueError("Expected success status must be between 100 and 599.")
    if not 400 <= int(expected_bad_request_status) <= 499:
        raise ValueError("Expected validation status should normally be a 4xx code.")
    if not 400 <= int(expected_unauthorized_status) <= 499:
        raise ValueError("Expected authentication status should normally be a 4xx code.")

    # Defence in depth: ensure the generator itself does not propagate common secrets
    # even if a caller forgets to invoke redact_curl beforehand.
    curl = redact_curl(curl)
    parsed = parse_curl(curl)
    url_parts = urlsplit(parsed["url"])
    if not url_parts.scheme or not url_parts.netloc:
        raise ValueError("The cURL must contain an absolute HTTP or HTTPS URL.")
    # Strip optional URL user-info before writing base URI into generated source.
    hostname = url_parts.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"  # IPv6 host
    authority = hostname + (f":{url_parts.port}" if url_parts.port else "")
    base_uri = f"{url_parts.scheme}://{authority}"

    # Keep ordinary query parameters in the endpoint. Move credential-like query values
    # to environment variables so they are never embedded in generated source code.
    safe_query: list[tuple[str, str]] = []
    secret_query: dict[str, str] = {}
    for key, value in parse_qsl(url_parts.query, keep_blank_values=True):
        if re.search(r"(?i)(token|password|secret|api[_-]?key|apikey|auth|session|cookie|signature|jwt|credential)", key):
            env_key = re.sub(r"[^A-Za-z0-9]", "_", key).upper()
            secret_query[key] = "${" + (env_key or "QUERY_SECRET") + "}"
        else:
            safe_query.append((key, value))
    endpoint_path = url_parts.path or "/"
    if safe_query:
        endpoint_path += "?" + urlencode(safe_query, doseq=True)

    safe_class = _safe_class_name(class_name)
    safe_package = _safe_package_name(package_name)
    package_path = safe_package.replace(".", "/")
    body = parsed["body"]
    body_is_json = False
    body_secret_names: set[str] = set()
    if body is not None:
        try:
            body_object = json.loads(body)
            body_object = _replace_sensitive_body_values(body_object, body_secret_names)
            body = json.dumps(body_object, ensure_ascii=False, separators=(",", ":"))
            body_is_json = True
        except json.JSONDecodeError:
            body_is_json = False

    selected_fields = list(dict.fromkeys(required_fields or []))
    missing_field_variants: list[tuple[str, str]] = []
    for field in selected_fields:
        variant = _body_without_field(body or "", field)
        if variant is not None:
            missing_field_variants.append((field, variant))
    response_paths = [p.strip() for p in (response_paths or []) if p and p.strip()]

    headers = dict(parsed["headers"])
    if body is not None and not any(k.lower() == "content-type" for k in headers):
        headers["Content-Type"] = "application/json" if body_is_json else "text/plain"

    auth_header_names = {"authorization", "proxy-authorization", "x-api-key", "api-key", "apikey", "x-auth-token", "x-access-token", "x-refresh-token", "cookie", "set-cookie", "x-session-token"}
    has_auth = parsed.get("basic_auth", False) or any(re.search(r"(?i)(authorization|auth|api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|cookie|session|secret)", k) for k in headers) or bool(secret_query)
    include_auth_test = include_missing_auth and has_auth
    include_malformed_test = include_malformed_json and body is not None and body_is_json and any(
        k.lower() == "content-type" and "json" in v.lower() for k, v in headers.items()
    )

    header_rows = [f"        headers.put({_java_literal(key)}, {_java_literal(value)});" for key, value in headers.items()]
    header_setup = "\n".join(header_rows) if header_rows else "        // No explicit headers were present in the cURL."
    query_rows = [f"        queryParams.put({_java_literal(k)}, {_java_literal(v)});" for k, v in secret_query.items()]
    query_setup = "\n".join(query_rows) if query_rows else "        // No credential-like query parameters detected."

    body_literal = "null" if body is None else _java_literal(body)
    method_literal = _java_literal(parsed["method"].upper())
    endpoint_literal = _java_literal(endpoint_path)
    base_uri_literal = _java_literal(base_uri)

    test_methods: list[str] = [
        """    @Test(description = \"Valid request returns the configured success status\")
    public void validRequestReturnsExpectedStatus() {
        Response response = execute(true, VALID_REQUEST_BODY);
        response.then().statusCode(EXPECTED_SUCCESS_STATUS);"""
    ]
    for path in response_paths:
        test_methods.append(f"        response.then().body({_java_literal(path)}, notNullValue());")
    test_methods.append("    }\n")

    if include_auth_test:
        test_methods.append("""    @Test(description = \"Request without authentication is rejected\")
    public void requestWithoutAuthenticationIsRejected() {
        Response response = execute(false, VALID_REQUEST_BODY);
        response.then().statusCode(EXPECTED_UNAUTHORIZED_STATUS);
    }
""")

    extra_constants: list[str] = []
    for idx, (field, variant) in enumerate(missing_field_variants, start=1):
        const_name = f"BODY_WITHOUT_REQUIRED_FIELD_{idx}"
        extra_constants.append(f"    private static final String {const_name} = {_java_literal(variant)};")
        test_methods.append(f"""    @Test(description = {_java_literal("Missing required field: " + field)})
    public void missingRequiredField{idx}IsRejected() {{
        Response response = execute(true, {const_name});
        response.then().statusCode(EXPECTED_BAD_REQUEST_STATUS);
    }}
""")

    if include_malformed_test:
        test_methods.append("""    @Test(description = \"Malformed JSON is rejected\")
    public void malformedJsonIsRejected() {
        Response response = execute(true, \"{malformed-json\");
        response.then().statusCode(EXPECTED_BAD_REQUEST_STATUS);
    }
""")

    extra_constant_section = "\n".join(extra_constants)
    if extra_constant_section:
        extra_constant_section = "\n" + extra_constant_section + "\n"

    test_source = fr'''package {safe_package}.tests;

import {safe_package}.support.RequestSpecFactory;
import io.restassured.response.Response;
import io.restassured.specification.RequestSpecification;
import org.testng.SkipException;
import org.testng.annotations.BeforeClass;
import org.testng.annotations.Test;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static io.restassured.RestAssured.given;
import static org.hamcrest.Matchers.notNullValue;

/** Generated starter. Confirm all statuses/assertions against the API contract. */
public class {safe_class} {{
    private static final String BASE_URI = System.getProperty("baseUri", {base_uri_literal});
    private static final String ENDPOINT = System.getProperty("endpoint", {endpoint_literal});
    private static final String HTTP_METHOD = {method_literal};
    private static final int EXPECTED_SUCCESS_STATUS = {int(expected_success_status)};
    private static final int EXPECTED_BAD_REQUEST_STATUS = {int(expected_bad_request_status)};
    private static final int EXPECTED_UNAUTHORIZED_STATUS = {int(expected_unauthorized_status)};
    private static final boolean BASIC_AUTH = {str(bool(parsed.get("basic_auth", False))).lower()};
    private static final String VALID_REQUEST_BODY = {body_literal};
{extra_constant_section}
    @BeforeClass(alwaysRun = true)
    public void requireExplicitIntegrationTestOptIn() {{
        if (!Boolean.getBoolean("runApiTests")) {{
            throw new SkipException("Safety guard: set -DrunApiTests=true only when targeting an approved test environment.");
        }}
    }}

    private static Map<String, String> requestHeaders() {{
        Map<String, String> headers = new LinkedHashMap<>();
{header_setup}
        return headers;
    }}

    private static Map<String, String> secretQueryParams() {{
        Map<String, String> queryParams = new LinkedHashMap<>();
{query_setup}
        return queryParams;
    }}

    private RequestSpecification requestSpec(boolean includeAuth) {{
        return RequestSpecFactory.create(BASE_URI, requestHeaders(), secretQueryParams(), includeAuth, BASIC_AUTH);
    }}

    private Response execute(boolean includeAuth, String body) {{
        RequestSpecification request = given().spec(requestSpec(includeAuth));
        if (body != null) {{
            request.body(resolveBodySecrets(body));
        }}
        return request.when().request(HTTP_METHOD, ENDPOINT);
    }}

    private static String resolveBodySecrets(String template) {{
        Pattern marker = Pattern.compile("__ENV_([A-Z0-9_]+)__");
        Matcher matcher = marker.matcher(template);
        StringBuffer resolved = new StringBuffer();
        while (matcher.find()) {{
            String value = RequestSpecFactory.requiredEnv(matcher.group(1));
            matcher.appendReplacement(resolved, Matcher.quoteReplacement(escapeJsonString(value)));
        }}
        matcher.appendTail(resolved);
        return resolved.toString();
    }}

    private static String escapeJsonString(String value) {{
        return value.replace("\\", "\\\\")
                .replace("\"", "\\\"")
                .replace("\b", "\\b")
                .replace("\f", "\\f")
                .replace("\n", "\\n")
                .replace("\r", "\\r")
                .replace("\t", "\\t");
    }}

{chr(10).join(test_methods)}
}}
'''

    support_source = f'''package {safe_package}.support;

import io.restassured.builder.RequestSpecBuilder;
import io.restassured.specification.RequestSpecification;

import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Reusable request setup. Secret values are loaded from environment variables. */
public final class RequestSpecFactory {{
    private static final Pattern ENV_PLACEHOLDER = Pattern.compile("^\\\\$\\\\{{([A-Z0-9_]+)}}$");
    private static final Pattern BEARER_PLACEHOLDER = Pattern.compile("(?i)^Bearer\\\\s+\\\\$\\\\{{([A-Z0-9_]+)}}$");

    private RequestSpecFactory() {{ }}

    public static RequestSpecification create(
            String baseUri,
            Map<String, String> headers,
            Map<String, String> secretQueryParams,
            boolean includeAuth,
            boolean basicAuth) {{
        RequestSpecBuilder builder = new RequestSpecBuilder().setBaseUri(baseUri);
        for (Map.Entry<String, String> entry : headers.entrySet()) {{
            String key = entry.getKey();
            String value = entry.getValue();
            if (isAuthHeader(key) && !includeAuth) {{
                continue;
            }}
            if (basicAuth && "Authorization".equalsIgnoreCase(key)) {{
                continue;
            }}
            builder.addHeader(key, resolveHeader(key, value));
        }}
        if (includeAuth) {{
            for (Map.Entry<String, String> entry : secretQueryParams.entrySet()) {{
                builder.addQueryParam(entry.getKey(), resolveEnvPlaceholder(entry.getValue()));
            }}
        }}
        if (basicAuth && includeAuth) {{
            String username = requiredEnv("API_USERNAME");
            String password = requiredEnv("API_PASSWORD");
            String raw = username + ":" + password;
            String encoded = Base64.getEncoder().encodeToString(raw.getBytes(StandardCharsets.UTF_8));
            builder.addHeader("Authorization", "Basic " + encoded);
        }}
        return builder.build();
    }}

    private static boolean isAuthHeader(String key) {{
        String normalized = key.toLowerCase();
        return normalized.matches(".*(authorization|auth|api[_-]?key|apikey|token|cookie|session|secret|signature|jwt|credential).*");
    }}

    private static String resolveHeader(String key, String value) {{
        Matcher bearer = BEARER_PLACEHOLDER.matcher(value);
        if ("Authorization".equalsIgnoreCase(key) && bearer.matches()) {{
            return "Bearer " + requiredEnv(bearer.group(1));
        }}
        return resolveEnvPlaceholder(value);
    }}

    private static String resolveEnvPlaceholder(String value) {{
        Matcher matcher = ENV_PLACEHOLDER.matcher(value);
        if (matcher.matches()) {{
            return requiredEnv(matcher.group(1));
        }}
        return value;
    }}

    public static String requiredEnv(String name) {{
        String value = System.getenv(name);
        if (value == null || value.isBlank()) {{
            throw new IllegalStateException("Required environment variable is not set: " + name);
        }}
        return value;
    }}
}}
'''

    pom = '''<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example.qa</groupId><artifactId>generated-api-tests</artifactId><version>1.0.0-SNAPSHOT</version>
  <properties>
    <maven.compiler.release>17</maven.compiler.release>
    <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
    <rest-assured.version>5.5.0</rest-assured.version><testng.version>7.10.2</testng.version>
  </properties>
  <dependencies>
    <dependency><groupId>io.rest-assured</groupId><artifactId>rest-assured</artifactId><version>${rest-assured.version}</version><scope>test</scope></dependency>
    <dependency><groupId>org.testng</groupId><artifactId>testng</artifactId><version>${testng.version}</version><scope>test</scope></dependency>
  </dependencies>
  <build><plugins>
    <plugin><groupId>org.apache.maven.plugins</groupId><artifactId>maven-compiler-plugin</artifactId><version>3.13.0</version><configuration><release>17</release></configuration></plugin>
    <plugin><groupId>org.apache.maven.plugins</groupId><artifactId>maven-surefire-plugin</artifactId><version>3.2.5</version></plugin>
  </plugins></build>
</project>
'''

    env_names: set[str] = set(body_secret_names)
    if parsed.get("basic_auth"):
        env_names.update(["API_USERNAME", "API_PASSWORD"])
    for value in headers.values():
        env_names.update(re.findall(r"\$\{([A-Z0-9_]+)\}", value))
    for value in secret_query.values():
        env_names.update(re.findall(r"\$\{([A-Z0-9_]+)\}", value))
    env_lines = "\n".join(f"set {name}=YOUR_TEST_VALUE" for name in sorted(env_names)) or "REM No environment-based credentials detected for this cURL."

    test_design_lines = [
        "# Generated Test Design and Assumptions", "",
        f"- Method: `{parsed['method'].upper()}`", f"- Base URI: `{base_uri}`", f"- Endpoint path: `{endpoint_path}`",
        f"- Expected success status: `{int(expected_success_status)}` (confirm contract).",
        f"- Expected validation status: `{int(expected_bad_request_status)}` (confirm contract).",
        f"- Expected authentication status: `{int(expected_unauthorized_status)}` (confirm contract).",
        f"- Required fields selected: `{', '.join(selected_fields) if selected_fields else 'none'}`.",
        f"- Response paths asserted non-null: `{', '.join(response_paths) if response_paths else 'none'}`.",
        "", "## Test cases", "", "1. Valid request returns the configured success status.",
    ]
    if response_paths:
        test_design_lines.append("2. Configured response paths are asserted non-null.")
    if include_auth_test:
        test_design_lines.append("- Request without authentication should return the configured authentication status.")
    for field, _ in missing_field_variants:
        test_design_lines.append(f"- Request missing `{field}` should return the configured validation status.")
    if include_malformed_test:
        test_design_lines.append("- Malformed JSON should return the configured validation status.")
    test_design_lines += [
        "", "## Before running", "", "- Verify expected statuses, required fields, response paths, authorization rules, and error schema against an approved API contract.",
        "- Verify that the target is a non-production/test environment and test data is safe.",
        "- Configure environment variables; credentials are not embedded in the generated source.",
        "- The suite skips unless `-DrunApiTests=true` is supplied.",
        "- cURL alone cannot prove business rules. Negative cases are hypotheses to validate with a requirement or API owner.",
    ]

    readme = f'''# Generated RestAssured + TestNG API test project

A generated integration-test starter based on a cURL request. It separates common request setup from endpoint tests, reads credentials from environment variables, includes configurable negative cases, and skips by default to protect against accidental live API calls.

## Files
- `pom.xml` — Maven dependencies and compiler configuration.
- `src/test/java/{package_path}/support/RequestSpecFactory.java` — reusable request setup, auth header resolution, environment-variable secrets, and query parameters.
- `src/test/java/{package_path}/tests/{safe_class}.java` — API-specific positive and selected negative tests.
- `TEST_DESIGN.md` — generated test scenarios and assumptions.

## Prerequisites
- JDK 17 or newer
- Maven 3.8+
- Network access to Maven dependencies and an approved test endpoint

## Configure credentials
Only set variables needed by the original request. For Windows Command Prompt:

```bat
{env_lines}
```

Replace the placeholder values with credentials for a non-production test environment. Never commit credentials.

## Run safely
The generated tests skip by default. Review the source and confirm the target environment before opting in:

```bat
mvn test -DrunApiTests=true -DbaseUri="{base_uri}" -Dendpoint="{endpoint_path}"
```

Override both `baseUri` and `endpoint` to target your QA environment. Do not run against production without explicit authorization and a suitable test-data plan.

## Important
The generator cannot infer the true API contract from cURL alone. Validate status codes, required fields, response JSON paths, authentication rules, error payloads, cleanup, and idempotency. Then adapt the project to your team's base classes, reporting, logging, tags, and CI pipeline.
'''

    return {
        "pom.xml": pom,
        f"src/test/java/{package_path}/support/RequestSpecFactory.java": support_source,
        f"src/test/java/{package_path}/tests/{safe_class}.java": test_source,
        "README.md": readme,
        "TEST_DESIGN.md": "\n".join(test_design_lines) + "\n",
    }


def restassured_project_zip(project_files: dict[str, str]) -> bytes:
    """Package generated project files into an in-memory ZIP archive."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, content in project_files.items():
            archive.writestr(path, content)
    return buffer.getvalue()
