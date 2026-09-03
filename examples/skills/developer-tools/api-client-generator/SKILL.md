---
name: api-client-generator
description: Generates a typed client for a REST or GraphQL API from its OpenAPI/GraphQL schema - matching the target codebase's existing HTTP client and error-handling conventions rather than introducing a new pattern. Use when asked to generate, scaffold, or write an API client from a schema or spec.
---

# API Client Generator

Given a `schemaPath` or `schemaUrl` (OpenAPI/GraphQL) and a target
language/codebase:

1. **Find the codebase's existing HTTP pattern first** - an existing API
   client, the HTTP library already in `package.json`/`requirements.txt`/
   etc., and its error-handling convention (thrown exceptions vs. result
   objects). Match it; don't introduce a second pattern.
2. **Parse the schema for what actually matters**: endpoints/operations,
   required vs. optional parameters, response shapes, and declared error
   responses - not just the happy-path 200.
3. **Generate one function/method per operation**, named from the
   schema's `operationId` (or a sensibly derived name if absent), not a
   single generic `request(path, method, body)` escape hatch that defeats
   the point of typing.
4. **Type request and response bodies** from the schema's models - reuse
   an existing shared types directory if the codebase has one, don't
   duplicate type definitions the schema already implies exist elsewhere.
5. **Handle pagination and auth exactly as the schema declares**
   (cursor/offset params, bearer/API-key headers) - don't assume a
   convention the schema doesn't state.
6. **Surface errors using the codebase's existing convention** from step
   1, including the schema's documented error response shapes, not a
   generic "request failed" string that throws away the response body.
7. **Do not hand-invent endpoints not in the schema** - if the ask
   implies functionality the schema doesn't expose, say so rather than
   guessing at an endpoint shape.
8. **Report what was generated**: file(s) written, operation count, and
   any schema ambiguity that required a judgment call.
