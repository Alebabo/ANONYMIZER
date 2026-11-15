# Third-party notices

## Langfuse (MIT)

The dashboard design tokens (`app/globals.css`) and the UI primitives in
`components/ui/` (button, card, table, input) are derived from
https://github.com/langfuse/langfuse (`web/src/styles/globals.css`,
`web/src/components/ui/`). Only files outside Langfuse's `ee/` directories
were used. The audit log record shape (`packages/core/src/cato/audit.py`:
resource type/id, action, before/after, actor) follows Langfuse's
`web/src/features/audit-logs/auditLog.ts` (MIT). The audit log viewer is Cato's
own implementation; Langfuse's viewer lives in `ee/` and was not used.
License text as distributed by Langfuse:

```
Copyright (c) 2023-2026 ClickHouse, Inc.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
