"""Generate source additions for a user's existing RestAssured/TestNG framework."""
from __future__ import annotations
import json
import re
from urllib.parse import urlsplit, parse_qsl, urlencode
from typing import Any

from qa_core import (
    redact_curl, parse_curl, _safe_class_name, _safe_package_name,
    _replace_sensitive_body_values, _body_without_field,
)


def build_restcommon_framework_patch(
    curl: str,
    *,
    class_name: str = "GeneratedOrderScenarios",
    test_package: str = "com.restapitest.orders",
    constants_package: str = "com.restapitest.constants",
    helper_package: str = "com.restapitest.util",
    constants_class_name: str = "GeneratedOrderApiConstants",
    rest_common_fqcn: str = "com.restapitest.common.RestCommon",
    rest_common_method: str = "getRequestSpecification",
    rest_common_static: bool = True,
    expected_success_status: int = 201,
    expected_bad_request_status: int = 400,
    required_fields: list[str] | None = None,
    response_paths: list[str] | None = None,
    include_malformed_json: bool = True,
) -> dict[str, str]:
    """Return integration-ready source files; no POM or duplicate RestCommon is created.

    The archive supplied for inspection did not contain Java source files. Therefore the
    RestCommon getter class/method are configurable and must be verified against the user's
    actual RestCommon.java before compiling.
    """
    if not 100 <= int(expected_success_status) <= 599:
        raise ValueError("Expected success status must be between 100 and 599.")
    if not 400 <= int(expected_bad_request_status) <= 499:
        raise ValueError("Expected validation status should normally be a 4xx code.")

    parsed = parse_curl(redact_curl(curl))
    parts = urlsplit(parsed["url"])
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError("The cURL must include an absolute HTTP or HTTPS URL.")

    safe_test_class = _safe_class_name(class_name)
    safe_constants_class = _safe_class_name(constants_class_name)
    test_package = _safe_package_name(test_package)
    constants_package = _safe_package_name(constants_package)
    helper_package = _safe_package_name(helper_package)

    common_parts = rest_common_fqcn.strip().split(".")
    if len(common_parts) < 2:
        raise ValueError("RestCommon class must be fully qualified, e.g. com.restapitest.common.RestCommon")
    common_class = _safe_class_name(common_parts[-1])
    common_package = _safe_package_name(".".join(common_parts[:-1]))
    method_name = rest_common_method.strip()
    if not re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", method_name) or method_name in {"class", "static", "public", "private", "return", "new", "void", "null", "this"}:
        raise ValueError("RestCommon getter must be a valid Java method name, e.g. getRequestSpecification")
    getter_call = (common_class + "." if rest_common_static else "new " + common_class + "().") + method_name + "()"

    method = parsed.get("method", "GET").upper()
    body = parsed.get("body")
    body_is_json = False
    secret_names: set[str] = set()
    if body is not None:
        try:
            body_object = json.loads(body)
            body_object = _replace_sensitive_body_values(body_object, secret_names)
            body = json.dumps(body_object, ensure_ascii=False, separators=(",", ":"))
            body_is_json = isinstance(body_object, (dict, list))
        except (json.JSONDecodeError, TypeError):
            body_is_json = False

    # RestCommon owns auth. Do not copy authentication headers from the cURL.
    ignored_headers = {
        "authorization", "proxy-authorization", "content-type", "content-length", "host",
        "connection", "accept-encoding", "cookie", "set-cookie", "user-agent"
    }
    extra_headers: dict[str, str] = {}
    for key, value in parsed.get("headers", {}).items():
        if key.lower() in ignored_headers or re.search(
            r"(?i)(authorization|auth|api[_-]?key|apikey|token|cookie|session|secret|credential)", key
        ):
            continue
        extra_headers[key] = value

    query_items = parse_qsl(parts.query, keep_blank_values=True)
    safe_query: list[tuple[str, str]] = []
    removed_query_keys: list[str] = []
    for key, value in query_items:
        if re.search(r"(?i)(token|password|secret|api[_-]?key|apikey|auth|session|cookie|signature|jwt|credential)", key):
            removed_query_keys.append(key)
        else:
            safe_query.append((key, value))
    endpoint_path = parts.path or "/"
    if safe_query:
        endpoint_path += "?" + urlencode(safe_query, doseq=True)

    def jlit(value: str) -> str:
        # JSON string escaping is compatible with Java string literals for these ordinary values.
        return json.dumps(value, ensure_ascii=True)

    selected_fields = list(dict.fromkeys(required_fields or []))
    variants: list[tuple[str, str, str]] = []
    for index, field in enumerate(selected_fields, start=1):
        variant = _body_without_field(body or "", field)
        if variant is not None:
            normalized = re.sub(r"[^A-Za-z0-9]+", "_", field).strip("_").upper() or f"FIELD_{index}"
            variants.append((field, f"BODY_WITHOUT_{normalized}", variant))

    paths = [item.strip() for item in (response_paths or []) if item and item.strip()]
    constants_class_path = f"src/test/java/{constants_package.replace('.', '/')}/{safe_constants_class}.java"
    helper_path = f"src/test/java/{helper_package.replace('.', '/')}/RestApiHelper.java"
    test_path = f"src/test/java/{test_package.replace('.', '/')}/{safe_test_class}.java"

    variant_constants = "\n".join(
        f"    public static final String {const_name} = {jlit(variant)};"
        for _field, const_name, variant in variants
    )
    if variant_constants:
        variant_constants = "\n" + variant_constants + "\n"

    header_lines = []
    env_names = set(secret_names)
    for key, value in extra_headers.items():
        header_lines.append(f"        headers.put({jlit(key)}, {jlit(value)});")
        env_names.update(re.findall(r"\$\{([A-Z0-9_]+)\}", value))
    header_block = "\n".join(header_lines) if header_lines else "        // Add non-auth custom headers here when needed."

    path_values = ", ".join(jlit(path) for path in paths)
    body_literal = "null" if body is None else jlit(body)
    constants_source = f'''package {constants_package};

import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** All generated endpoint constants are centralized here. Review before use. */
public final class {safe_constants_class} {{
    private {safe_constants_class}() {{ }}

    // Base URI/environment selection stays inside RestCommon.
    public static final String API_PATH = {jlit(endpoint_path)};
    public static final String HTTP_METHOD = {jlit(method)};
    public static final int EXPECTED_SUCCESS_STATUS = {int(expected_success_status)};
    public static final int EXPECTED_BAD_REQUEST_STATUS = {int(expected_bad_request_status)};
    public static final String VALID_REQUEST_BODY = {body_literal};
{variant_constants}
    public static final List<String> RESPONSE_JSON_PATHS = Collections.unmodifiableList(
            Arrays.asList({path_values}));

    public static final Map<String, String> EXTRA_HEADERS;
    static {{
        Map<String, String> headers = new LinkedHashMap<>();
{header_block}
        EXTRA_HEADERS = Collections.unmodifiableMap(headers);
    }}
}}
'''

    helper_source = f'''package {helper_package};

import {common_package}.{common_class};
import {constants_package}.{safe_constants_class};
import io.restassured.http.ContentType;
import io.restassured.response.Response;
import io.restassured.specification.RequestSpecification;
import org.json.JSONObject;

import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Common execution and assertion methods used by generated API tests. */
public final class RestApiHelper {{
    private static final Pattern BODY_ENV = Pattern.compile("__ENV_([A-Z0-9_]+)__");
    private static final Pattern HEADER_ENV = Pattern.compile("^\\\\$\\\\{{([A-Z0-9_]+)\\\\}}$");

    private RestApiHelper() {{ }}

    /** The only integration seam to the existing RestCommon configuration. */
    public static RequestSpecification getRequestSpecification() {{
        RequestSpecification specification = {getter_call};
        // This should be a fresh RequestSpecification per test invocation.
        for (Map.Entry<String, String> header : {safe_constants_class}.EXTRA_HEADERS.entrySet()) {{
            specification.header(header.getKey(), resolveHeaderValue(header.getValue()));
        }}
        return specification;
    }}

    public static Response sendRequest(String method, String endpointPath, String body) {{
        RequestSpecification specification = getRequestSpecification();
        if (body != null && !body.isBlank()) {{
            specification.contentType(ContentType.JSON).body(resolveBodySecrets(body));
        }}
        return specification.when().request(method, endpointPath);
    }}

    public static void assertStatusCode(Response response, int expectedStatus) {{
        response.then().statusCode(expectedStatus);
    }}

    public static void assertConfiguredResponsePaths(Response response) {{
        for (String jsonPath : {safe_constants_class}.RESPONSE_JSON_PATHS) {{
            response.then().body(jsonPath, org.hamcrest.Matchers.notNullValue());
        }}
    }}

    /** Reusable helper for data-driven negative tests. */
    public static String withoutTopLevelJsonField(String body, String fieldName) {{
        JSONObject json = new JSONObject(body);
        json.remove(fieldName);
        return json.toString();
    }}

    private static String resolveHeaderValue(String value) {{
        Matcher matcher = HEADER_ENV.matcher(value);
        if (!matcher.matches()) return value;
        String resolved = System.getenv(matcher.group(1));
        if (resolved == null || resolved.isBlank()) {{
            throw new IllegalStateException("Missing required environment variable: " + matcher.group(1));
        }}
        return resolved;
    }}

    private static String resolveBodySecrets(String body) {{
        Matcher matcher = BODY_ENV.matcher(body);
        StringBuffer output = new StringBuffer();
        while (matcher.find()) {{
            String name = matcher.group(1);
            String value = System.getenv(name);
            if (value == null) throw new IllegalStateException("Missing required environment variable: " + name);
            matcher.appendReplacement(output, Matcher.quoteReplacement(escapeJson(value)));
        }}
        matcher.appendTail(output);
        return output.toString();
    }}

    private static String escapeJson(String value) {{
        return value.replace("\\\\", "\\\\\\\\")
                .replace("\\\"", "\\\\\\\"")
                .replace("\\n", "\\\\n")
                .replace("\\r", "\\\\r")
                .replace("\\t", "\\\\t");
    }}
}}
'''

    test_methods = [f'''    @Test(description = "Valid request returns expected status and configured response fields")
    public void validRequestReturnsExpectedStatus() {{
        Response response = RestApiHelper.sendRequest(
                {safe_constants_class}.HTTP_METHOD,
                {safe_constants_class}.API_PATH,
                {safe_constants_class}.VALID_REQUEST_BODY);
        RestApiHelper.assertStatusCode(response, {safe_constants_class}.EXPECTED_SUCCESS_STATUS);
        RestApiHelper.assertConfiguredResponsePaths(response);
    }}
''']
    for field, const_name, _variant in variants:
        method_suffix = re.sub(r"[^A-Za-z0-9]+", " ", field).title().replace(" ", "") or "Field"
        test_methods.append(f'''    @Test(description = {jlit("Missing required field: " + field)})
    public void missing{method_suffix}IsRejected() {{
        Response response = RestApiHelper.sendRequest(
                {safe_constants_class}.HTTP_METHOD,
                {safe_constants_class}.API_PATH,
                {safe_constants_class}.{const_name});
        RestApiHelper.assertStatusCode(response, {safe_constants_class}.EXPECTED_BAD_REQUEST_STATUS);
    }}
''')
    if include_malformed_json and body is not None and body_is_json:
        test_methods.append(f'''    @Test(description = "Malformed JSON is rejected")
    public void malformedJsonIsRejected() {{
        Response response = RestApiHelper.sendRequest(
                {safe_constants_class}.HTTP_METHOD,
                {safe_constants_class}.API_PATH,
                "{{malformed-json");
        RestApiHelper.assertStatusCode(response, {safe_constants_class}.EXPECTED_BAD_REQUEST_STATUS);
    }}
''')

    test_source = f'''package {test_package};

import {constants_package}.{safe_constants_class};
import {helper_package}.RestApiHelper;
import io.restassured.response.Response;
import org.testng.annotations.Test;

/** Endpoint-specific TestNG tests generated for the existing framework. */
public class {safe_test_class} {{
{''.join(test_methods)}
}}
'''
    testng_snippet = f'''<!-- Add this entry to the existing testng.xml <classes> section; preserve current entries. -->
<class name="{test_package}.{safe_test_class}" />
'''

    env_lines = "\n".join(f"set {name}=YOUR_TEST_VALUE" for name in sorted(env_names)) or "REM Auth is configured by RestCommon or the existing environment setup."
    integration_notes = f'''# RestCommon framework integration notes

## What was available in the uploaded ZIP

The archive included `pom.xml`, `testng.xml`, test reports and package-directory names under `com.restapitest`, but it did **not** contain any `.java` source files. I therefore could not inspect the exact `RestCommon` getter signature.

## Files generated

- `{constants_package.replace('.', '/')}/{safe_constants_class}.java`: centralized endpoint, method, statuses, request body, response JSON paths and extra non-auth headers.
- `{helper_package.replace('.', '/')}/RestApiHelper.java`: shared send-request, status assertion, JSON path assertion and request-body helper methods. It obtains the `RequestSpecification` through your existing `RestCommon`.
- `{test_package.replace('.', '/')}/{safe_test_class}.java`: endpoint-specific TestNG scenarios.
- `testng.xml.snippet`: add this single class to the existing suite; do not replace `testng.xml`.

No new `pom.xml` or duplicate `RestCommon` is generated. The helper is intended to be copied into the existing Maven project, which already declares RestAssured and TestNG.

## The one line to verify

The generated helper calls:

```java
{getter_call}
```

This assumes that the getter returns `io.restassured.specification.RequestSpecification`. If your real method has another name, is an instance method, or accepts arguments, change the generator setting or adapt that line before compiling.

`RestCommon` should return a **new RequestSpecification for each test call**; a shared mutable instance risks headers/body leaking between requests.

## Intended design

- Base URI and environment configuration remain in `RestCommon`.
- API-specific values live in `{safe_constants_class}`.
- Reusable request execution and assertions live in `RestApiHelper`.
- Endpoint-specific TestNG cases live in `{safe_test_class}`.
- Authentication is deliberately delegated to `RestCommon`; auth values from cURL are not copied into tests.
- The cURL host is not used to override the framework base URI. Confirm that `API_PATH` is valid against your QA/STG/SB environment.

## Validate before running

1. Compare the import and getter call with the actual `RestCommon.java`.
2. Check `API_PATH`, expected status codes, required fields and response JSON paths against Swagger/API requirements.
3. Confirm `RestCommon` returns fresh request specifications.
4. Merge `testng.xml.snippet` into the current `<classes>` list.
5. Run only this test class against an approved non-production environment first.

Credential placeholders, when present, need values in the test environment. For Windows CMD, names may be configured like:

```bat
{env_lines}
```
'''

    design_lines = [
        "# Generated API test design", "",
        f"- Method: `{method}`", f"- Path: `{endpoint_path}`",
        f"- Expected success status: `{int(expected_success_status)}` (confirm contract).",
        f"- Expected validation status: `{int(expected_bad_request_status)}` (confirm contract).",
        f"- Required fields selected: `{', '.join(selected_fields) if selected_fields else 'none'}`.",
        f"- Response paths asserted non-null: `{', '.join(paths) if paths else 'none'}`.",
        "", "## Generated scenarios", "", "1. Valid request and configured response assertions.",
    ]
    design_lines.extend(f"- Request without `{field}` should return the configured validation status." for field, _, _ in variants)
    if include_malformed_json and body is not None and body_is_json:
        design_lines.append("- Malformed JSON request should return the configured validation status.")
    if removed_query_keys:
        design_lines.append("- Sensitive query parameters excluded from generated path: " + ", ".join(removed_query_keys) + ". Configure them through the approved framework mechanism if required.")
    design_lines += ["", "## Notes", "", "- This is a source patch for an existing framework, not a standalone Maven project.", "- Generated expectations must be checked against the API contract.", "- A no-auth test is omitted because auth is owned by RestCommon and its implementation was not included in the uploaded archive."]

    return {
        constants_class_path: constants_source,
        helper_path: helper_source,
        test_path: test_source,
        "testng.xml.snippet": testng_snippet,
        "docs/GENERATED_API_TEST_DESIGN.md": "\n".join(design_lines) + "\n",
        "docs/RESTCOMMON_INTEGRATION.md": integration_notes,
    }
