# Operator Console Frontend Design Guidelines

This document defines the visual and interaction system for the Agentic Customer Service Platform operator console. It is a design and implementation constraint for future frontend work; it does not change backend contracts or agent behavior.

## Visual direction

The console is an operator/debug surface for an AI agent infrastructure platform, not a customer-facing chatbot. It should communicate control, traceability, and operational confidence.

Use a quiet dark workspace with clear panel boundaries, compact metadata, and a strong top-level run hierarchy. Prefer one cohesive workspace over a wall of unrelated floating cards. The primary composition is:

```text
agent run header
conversation workspace        tabbed agent inspector
timeline / resilience / system status
```

Use progressive disclosure: show the run outcome and key decision metadata first, then let operators inspect tools, policy, RAG, memory, and trace details through tabs or focused sections.

## Typography

- Use a neutral system sans stack for interface text and a monospace face only for IDs, event names, and bounded technical values.
- Establish a clear scale: page title, section title, card title, metadata label, then value.
- Use weight and spacing to establish hierarchy; do not make every label bold or uppercase.
- Keep body text readable at approximately 14–16px and supporting metadata at 11–13px.
- Use sentence case for human-facing copy. Reserve uppercase/letter spacing for compact labels and statuses.
- Truncate long IDs visually, but preserve the full value for copy/accessibility affordances when appropriate.

## Spacing and layout

- Use a consistent 4px base spacing scale, with common rhythm at 8, 12, 16, 20, and 24px.
- Align panel content to shared page gutters and column baselines.
- Keep desktop density high enough for operations work without compressing controls below comfortable touch/keyboard targets.
- Use responsive grid/flex layouts; avoid fixed widths that break on smaller laptops.
- Group related information by purpose: conversation, decision, execution, evidence, memory, and system health.
- Avoid nesting many bordered cards. Use dividers, whitespace, and section headers when a second container is unnecessary.

## Component rules

Shared primitives belong in `frontend/src/components/ui/` and should expose typed, semantic props. Prefer these primitives where relevant:

- `Card` / `Panel`: one surface language with optional density and emphasis;
- `Badge` / `StatusIndicator`: bounded semantic states, not decoration;
- `MetricCard`: only for genuinely important run metrics;
- `Timeline`: ordered execution or trace events with status and duration;
- `Tabs`: keyboard-navigable progressive disclosure for inspector domains;
- `SectionHeader`: consistent title, description, and optional actions;
- `EmptyState` / `Skeleton`: purposeful empty and loading states;
- `DataRow`: aligned label/value metadata;
- `Tooltip`: supplementary explanations, never the sole place for essential information.

Components should have one responsibility, avoid duplicated Tailwind class strings where a shared pattern exists, and preserve clear focus/hover/disabled states.

## Color and status

Use a restrained neutral foundation and semantic accents only when they convey meaning:

| Meaning | Color treatment |
| --- | --- |
| Success / healthy / executed | green or mint |
| Warning / confirmation / degraded | amber |
| Failure / denied / unavailable | red |
| Informational / selected / link | blue |
| Neutral metadata | slate/gray |

Do not color every panel or label. Status must not rely on color alone: pair it with text, an icon, or a shape. Keep contrast strong in dark mode, especially for small metadata.

## Accessibility

- Use semantic landmarks: header, main, nav/tablist, section, form, and footer where appropriate.
- Every control needs an accessible name; every input needs a visible label or an equivalent label.
- Make all interactive elements keyboard reachable in a logical order.
- Use visible `:focus-visible` styles with sufficient contrast.
- Tabs must expose selected state with `aria-selected`, keyboard navigation, and associated tab panels.
- Provide `aria-live` feedback for request progress and errors without interrupting unrelated reading.
- Do not use color as the only indicator of status.
- Respect reduced-motion preferences for transitions and timeline appearance.
- Keep minimum interactive target sizes comfortable for touch and operator use.

## Loading, empty, and error states

Loading states should communicate the operation in progress with a skeleton or progressive status such as “Retrieving knowledge…”, “Evaluating policy…”, or “Executing tool…”. Avoid unexplained spinners or plain “Loading” text.

Empty states should explain what is absent and what the operator can do next, for example:

- “Select a customer to start an agent session.”
- “Run an agent request to generate execution data.”
- “No persistent customer memory found.”

Errors should be bounded, actionable, and free of raw exceptions or sensitive payloads.

## Animation

Use minimal motion for panel transitions, timeline appearance, and status changes. Prefer short opacity/transform transitions that preserve orientation. Avoid bouncing, looping decoration, flashy gradients, and motion that delays access to information. Honor `prefers-reduced-motion`.

## Dashboard principles

- Make the current agent run the primary object of attention.
- Put intent, request type, status, risk, latency, and components used in the overview.
- Use a tabbed inspector instead of one long debug page.
- Present tools as an execution timeline with risk and status, never raw arguments.
- Present policy as structured outcomes and validation checkpoints, never hidden reasoning.
- Present RAG as source metadata and scores, never raw retrieved content by default.
- Make persistent memory visibly contextual and explicitly state that it cannot authorize actions.
- Present traces as bounded event timelines, never chain-of-thought.
- Present resilience as dependency health and recovery actions, never raw exception strings.
- Keep customer, conversation, run, and trace identifiers correlated but visually secondary to the decision outcome.
