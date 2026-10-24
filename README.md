# AI QA Engineering Agent (Portfolio MVP)

A QA engineering proof-of-concept (updated API project generator, v0.2) with three workflows:

1. **Test Intelligence** — turn a user story and project rules into structured test cases and export CSV.
2. **API Automation** — parse common cURL inputs and generate a Java + RestAssured + TestNG starter test.
3. **Self-Healing Lab** — classify failure evidence and propose a reviewable fix workflow with a human approval gate.

The app can run without an API key in **template/rule-based mode**. Configure an OpenAI API key to enable AI-assisted generation. A ChatGPT subscription does not automatically include API usage; check your API platform billing before enabling it.

See [CHANGELOG.md](CHANGELOG.md) for the current API project-generator improvements.

## Quick start on Windows

1. Install Python. Then extract this repository to a folder such as `D:\projects\ai_qa_fasttrack`.
2. Open Command Prompt in that folder.
3. Run:

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m streamlit run app.py
```

4. Open the local URL printed in the terminal (usually `http://localhost:8501`).
5. Use the sample user story or cURL already loaded in the app. Try template mode first.


## Use Markdown project guidance

The **Test Intelligence** tab now accepts one or more uploaded `.md`, `.markdown`, or `.txt` files. For example, upload `samples/org_qa_guidelines.md` to provide synthetic API rules, validation requirements, security expectations, and regression scenarios. The app combines this material with the user story and any manually entered context.

- In **AI mode**, the uploaded material is included in the generation prompt so the configured model can derive more project-specific test cases.
- In **template mode**, the file can be loaded and previewed, but test generation is only deterministic and keyword-based; it does not semantically understand the document. Do not describe template-mode output as AI-generated.
- Files are processed in the current app session and are not permanently learned, indexed, or used to train a model by this application. A real retrieval/knowledge-base feature would be a separate enhancement.
- The demo accepts plain-text Markdown/text formats only and applies a combined character limit. Do not upload secrets, proprietary company documents, personal data, or production payloads to an external model without approval.

## API Automation: generate a reusable Maven project

The API Automation tab offers three paths:

- **Quick single-class preview** — a minimal starter for quick inspection.
- **Generate source files for your existing RestCommon framework** — preferred when integrating with an existing `com.restapitest`-style repository.
- **Generate a standalone RestAssured framework project** — useful for a fresh demo repository with a new POM and request helper. It creates a downloadable project ZIP containing `pom.xml`, a reusable `RequestSpecFactory`, an endpoint-specific TestNG class, `README.md`, and `TEST_DESIGN.md`.

The project generator can:

- Parse the HTTP method, URL/path, headers, and JSON request body from common cURL forms.
- Move common authentication values and credential-like query parameters to environment variables rather than embedding them in generated source.
- Move sensitive JSON string values (for example passwords or client secrets) to runtime environment-variable placeholders.
- Generate a positive test with the configured expected status.
- Generate selected missing-field tests from top-level JSON properties, an optional missing-auth test, and an optional malformed-JSON test.
- Add optional response JSON-path assertions that the user supplies from the API contract.
- Separate reusable request setup from endpoint test logic and include a human-review/test-design note.

**Important:** cURL describes a request; it normally does not define the complete business contract. It cannot prove which fields are mandatory, what status code a negative request should return, or which response values must exist. Confirm these values against an OpenAPI/Swagger specification, acceptance criteria, or an API owner. The generated tests must be reviewed before use.

### Running the generated Java project

The Streamlit application itself requires Python. To compile and run a standalone generated Java project, the target laptop also needs JDK 17+ and Maven 3.8+ with access to Maven dependencies. The RestCommon source patch instead uses the existing project POM and its dependency setup. These are separate from the Python setup script.

Generated tests **skip by default**. After reviewing the generated files, configuring environment variables, and pointing at a safe non-production test environment, run from the generated project's folder:

```bat
mvn test -DrunApiTests=true -DbaseUri="https://your-qa-host.example" -Dendpoint="/api/your-endpoint"
```

Use the actual approved QA base URL and endpoint. The command intentionally requires the explicit `-DrunApiTests=true` flag so downloading or compiling a project does not automatically call an API. Never run generated negative tests against production without explicit authorization and a safe test-data plan.


## Example output for an existing RestCommon-style framework

See [`examples/RestCommon_Framework_Output/`](examples/RestCommon_Framework_Output/) for a synthetic example of the source patch produced by the framework-specific mode. It demonstrates:

- `constants/OrderApiConstants.java` for centralized path, method, expected statuses, body, headers and JSON paths;
- `util/RestApiHelper.java` for obtaining `RequestSpecification` from `RestCommon`, sending requests and common assertions;
- `orders/OrderScenarios.java` for endpoint-specific TestNG tests;
- a `testng.xml` snippet and implementation/validation notes.

The sample uses fictional order data. Its `RestCommon.getRequestSpecification()` signature is illustrative and must be aligned with the target framework before compilation. It is not bundled with or derived from any employer's private Java source code.

## Enable AI mode (optional)

- Create an API key from your authorised model-provider account.
- In the app sidebar, paste it in **Model API key**. The key is held in the current app session and is not written into this repository by the app.
- The default model is configurable. If it is not enabled on your account, use a model that your API account supports.
- API use may incur separate charges. Never commit keys to GitHub, and do not enter employer-owned documentation, production URLs, actual secrets, customer data, or proprietary payloads.

You can also set `OPENAI_API_KEY` and `OPENAI_MODEL` in your environment; never put a real key in a committed `.env` file.

## Run the core tests

```bat
python -m unittest discover -s tests -v
```
## Important limitations

- This is a portfolio prototype, not a production QA platform.
- Template mode uses deterministic rules and generic test patterns; it is **not** AI.
- cURL parsing supports common flags only. Review complex quoting, nested query logic, file uploads, OAuth flows, cookie files, multi-part uploads, and shell-specific syntax manually.
- The standalone Java generator is a framework starter. The RestCommon mode is designed as a source patch, but because the supplied framework archive had no Java source files, the exact RestCommon getter could not be verified. Align its method signature and packages, then validate base URL configuration, authentication utilities, response assertions, test data lifecycle, logging, reporting and CI integration before team use.
- The Self-Healing Lab does not automatically edit repositories, run arbitrary commands, push branches, or open pull requests. It demonstrates guarded analysis and review. A future CI/GitHub integration must run in an isolated workspace and preserve human approval before merge.
- Always review AI output for correctness, coverage, privacy, security, and alignment with acceptance criteria.

## Suggested architecture

```text
Streamlit UI
  ├─ Test Intelligence
  │    ├─ Requirement + project context
  │    ├─ AI generation (optional) / deterministic fallback
  │    └─ Structured cases → CSV
  ├─ API Automation
  │    ├─ Redact secrets and parse cURL
  │    ├─ Generate RestAssured/TestNG starter source
  │    └─ Human review before use
  └─ Self-Healing Lab
       ├─ Failure evidence
       ├─ AI-assisted / rule-based triage
       ├─ Proposed fix + verification plan
       └─ Human approval gate (demo only)
```
