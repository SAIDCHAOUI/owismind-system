Now I have enough material to compose the dense research report.

---

## State-of-the-Art Agentic / Conversational Analytics Assistants (2024-2026)

---

### 1. KEY FINDINGS

**Market direction (2025-2026): "Ask to Act", not "Search to Visualize".**
The dominant shift across all major platforms is from reactive Q&A toward autonomous, multi-step agentic workflows that proactively surface insights, draft narratives, and push digests. ThoughtSpot rebranded Sage to Spotter 3, explicitly positioning it as an "Autonomous Agent" ([TechTarget](https://www.techtarget.com/searchbusinessanalytics/news/366615693/ThoughtSpot-AI-agent-Spotter-enables-conversational-BI)). Databricks Genie ([Zenlytic overview](https://zenlytic.com/blog/databricks-ai-bi-genie)) and Snowflake Intelligence ([Snowflake.help](https://snowflake.help/snowflake-intelligence-your-gateway-to-ai-driven-insights/)) follow the same arc.

**The semantic layer is the non-negotiable accuracy unlock.**
Raw LLM on enterprise schemas achieves ~6-17% accuracy. Adding a well-authored semantic layer lifts this to 54%+; a full semantic + governance stack reaches 90%+ ([Promethium](https://promethium.ai/guides/conversational-analytics-ai-agents-enterprise-data-access-2026/), [AtScale](https://www.atscale.com/blog/build-trust-conversational-bi-semantic-layer/)). Every product that claims to be production-ready (Cortex Analyst, Genie, ThoughtSpot, Looker Gemini) is grounded in an explicit semantic/metric layer.

**Trust is the adoption bottleneck, not features.**
A survey of 20,000+ customers identified lack of trust (not cost or complexity) as the primary barrier ([Promethium](https://promethium.ai/guides/conversational-analytics-ai-agents-enterprise-data-access-2026/)). Organizations that deploy without governance see initial enthusiasm followed by gradual abandonment as inconsistent results erode confidence.

---

### 2. FEATURE TAXONOMY

#### A. Core NL Interaction
| Feature | Leaders |
|---|---|
| Natural-language Q&A over structured data | All (ThoughtSpot, Genie, Cortex Analyst, Looker, Power BI Copilot, Q in QuickSight) |
| Multi-turn follow-up ("now show only enterprise clients") | Looker Gemini, ThoughtSpot Spotter, Tableau Pulse, Hex Threads |
| Session memory / context carryover | Hex Threads ([hex.tech](https://hex.tech/blog/fall-2025-launch/)), Looker Conversational Analytics |
| Suggested follow-up questions | Tableau Pulse enhanced Q&A, Looker, Q in QuickSight |

#### B. Auto-Visualization & Dashboard Generation
| Feature | Leaders |
|---|---|
| Chart-type auto-selection from question intent | ThoughtSpot SpotterViz, Power BI Copilot, Looker Gemini |
| Full dashboard from natural language ("build a sales dashboard") | ThoughtSpot SpotterViz ([TechTarget](https://www.techtarget.com/searchbusinessanalytics/news/366636078/ThoughtSpot-automates-full-platform-with-new-Spotter-agents)), Hex App Builder |
| Instant slide decks from dashboards | Looker Gemini ([Google Cloud blog](https://cloud.google.com/blog/products/business-intelligence/a-closer-look-at-looker-conversational-analytics/)) |

#### C. Proactive Insights & Anomaly Detection
| Feature | Leaders |
|---|---|
| 24/7 background metric monitoring with push alerts | ThoughtSpot Spotter, Tableau Pulse (mobile/email/Slack/Teams - [Tableau](https://www.tableau.com/products/tableau-pulse)) |
| Anomaly + trend detection with plain-language explanation | Tableau Pulse (drivers, outliers, seasonality), Looker Code Interpreter (Python-powered forecasting) |
| Personalized daily/weekly digests | Tableau Pulse digests, Power BI Copilot briefings, Amazon Quick Suite executive summaries |
| Off-cycle alerts (critical threshold breach) | Tableau Pulse (up to 1 per day per metric) |

#### D. Narrative / Insight Summaries
| Feature | Leaders |
|---|---|
| Auto-generated written analysis accompanying charts | Tableau Pulse, ThoughtSpot Spotter, Looker Gemini, Amazon Q (data stories) |
| "Why did X happen?" root-cause analysis | Tableau Pulse (contributor analysis), ThoughtSpot (driver analysis) |
| Summarized multi-metric overview across followed metrics | Tableau Pulse Overview at top of digest |
| Executive briefing / digest generation | Amazon Quick Suite ([EPC Group](https://www.epcgroup.net/amazon-quicksight-vs-power-bi-enterprise-comparison)), Power BI Copilot |

#### E. Drill-Down / Decomposition
| Feature | Leaders |
|---|---|
| "Explain this number" / decomposition tree | Power BI Copilot, ThoughtSpot, Tableau Pulse (contributor breakdown) |
| Comparative analysis (vs. period, vs. segment) | Genie, Cortex Analyst, Hex Threads |
| What-if / forecasting | Looker Code Interpreter (generates Python), Hex Notebook Agent |

#### F. Governance, Explainability & Trust
| Feature | Leaders |
|---|---|
| Semantic layer grounding (metric definitions) | Cortex Analyst (semantic views), Genie (Unity Catalog), ThoughtSpot (patented semantic layer), Looker LookML |
| Show-your-work / SQL transparency | Databricks Genie (exposes generated logic), Cortex Analyst (API first, auditable), Qlik Answers (citations) |
| Verified answers / certified metrics | ThoughtSpot (verified search), Qlik Answers (explainable calculations with citations - [Qlik](https://www.qlik.com/us/products/qlik-answers)) |
| Role-based data access enforcement | All enterprise platforms; critical for multi-tenant trust |
| Audit trails (question → answer derivation) | AtScale semantic layer pattern, Promethium architecture |

#### G. Distribution & Sharing
| Feature | Leaders |
|---|---|
| Push to Slack / Teams / email | Tableau Pulse, Qlik, Power BI Copilot, Looker |
| PNG/PDF/PPT export | Power BI Copilot, Looker slide decks, Amazon Q |
| Embedded / API-first delivery | Cortex Analyst (REST API), ThoughtSpot Embedded (beta), Hex Apps |

#### H. Structured + Unstructured Data Fusion
| Feature | Leaders |
|---|---|
| NL over structured + document/PDF/image | Qlik Answers (structured + unstructured documents - [Qlik press](https://www.qlik.com/us/news/company/press-room/press-releases/qlik-answers-bridges-the-ai-gap-with-explainable-actionable-intelligence-at-scale)), Amazon Cortex AISQL |
| Knowledge base / enterprise search fusion | Glean (enterprise search + analytics fusion - [Tech Field Day](https://techfieldday.com/2025/glean-insights-value-from-unstructured-data-with-qlik-answers/)) |

---

### 3. PERSONA-TO-FEATURE MAP

| Persona | Top Decision-Value Features | Why |
|---|---|---|
| **Account Manager** (sell better, answer clients) | NL Q&A on customer revenue/usage, "why did client X drop?", comparison views vs. prior period, shareable chart export (PNG/email), mobile digest | Removes dependency on data team; answers client questions in-meeting; live revenue breakdown builds credibility |
| **Product Owner** | Usage trend + anomaly alerts, cohort drill-down, what-if/forecast, follow-up Q&A on feature adoption, narrative summaries for stakeholder updates | Reduces time-to-insight on feature KPIs; proactive alerts surface regressions before reviews |
| **Marketing Director** | Campaign performance NL Q&A, segment comparison, scheduled email digest, "explain this drop" root-cause, slide deck / briefing generation | Eliminates analyst bottleneck for campaign reporting; digest replaces manual weekly deck |
| **Executive / CEO** | Personalized morning digest (multi-metric overview), anomaly push alerts, plain-language narrative ("revenue fell 12% vs. prior week because..."), certified/verified answers only | Zero BI tool learning curve; trust requires certified metrics only; mobile-first delivery is critical |

**High-ROI features for OWIsMind's current user base:**
- Account managers + execs: **proactive digest** (push when a KPI moves), **"why did X happen"** decomposition, **shareable export**
- All personas: **follow-up suggestions** (reduces blank-page syndrome), **show-your-work SQL transparency** (builds trust)

---

### 4. COPYABLE UX PATTERNS

**a) "Explain This Number" button on every metric**
Clicking any figure triggers a decomposition: "Revenue is down 8% vs. last month. Main driver: Roaming Hub (-23%), partially offset by EVPL (+4%). No seasonality anomaly detected." Implemented by Tableau Pulse (Insight Types: contributor, outlier, top/bottom) and Power BI Copilot (decomposition tree). For OWIsMind: wire this as a follow-up intent on any numeric answer.

**b) Proactive digest push (Tableau Pulse pattern)**
Rather than waiting for users to ask, schedule a nightly scan: detect metrics that moved >X% or crossed a threshold, generate a 3-5 sentence narrative, and push via email/Slack. Tableau Pulse allows up to 1 off-cycle alert per day per metric ([Tableau help](https://help.tableau.com/current/online/en-us/pulse_insights_platform_insight_types.htm)). For OWIsMind: add a cron-driven digest agent that posts to email/Teams.

**c) Suggested follow-up chips after every answer**
After each response, surface 2-3 pre-generated follow-up questions ("Break down by region", "Compare to budget", "Show trend for 12 months"). Tableau Pulse, Looker, and Q in QuickSight all do this. Reduces blank-page syndrome; critical for non-technical users.

**d) Scope preamble ("Here is what I filtered")**
Every answer opens with a one-line scope statement: "Showing: Actuals / All years / All offers / EUR." Prevents silent hallucination of scope assumptions. Already prototyped in OWIsMind (orchestrator PERSONA directive) - align with this pattern explicitly.

**e) Escalation path ("Turn this into a deeper analysis")**
Hex Threads exposes an "open in notebook" escape hatch for data teams to audit/extend any answer ([hex.tech](https://hex.tech/blog/fall-2025-launch/)). For OWIsMind: link Evidence panel SQL as the audit escape hatch - you already have this.

**f) Comparison view ("vs. prior period / vs. budget")**
Pre-wire a "compare" intent: user says "revenues Q1" and the system automatically adds a prior-period column. All leaders do this. Reduces the need to re-ask.

---

### 5. PITFALLS LEADERS WARN ABOUT

| Pitfall | Concrete Evidence | Mitigation |
|---|---|---|
| **Silent wrong answers** (worse than hallucinations) | Raw LLM: 6-17% accuracy on real schemas; slightly wrong definitions spread through decisions undetected ([Promethium](https://promethium.ai/guides/conversational-analytics-ai-agents-enterprise-data-access-2026/)) | Semantic layer + verified/certified answers only; never serve raw LLM-generated SQL without a guardrail layer |
| **Metric inconsistency across tools** | Same question, different answer in different tools destroys trust ([AtScale](https://www.atscale.com/blog/build-trust-conversational-bi-semantic-layer/)) | Centralized semantic definitions (OWIsMind already has this via the Dataiku semantic model tool) |
| **Initial enthusiasm, later abandonment** | "Organizations... gradually abandon [the tool] as confidence erodes due to inconsistent results" ([Promethium](https://promethium.ai/guides/conversational-analytics-ai-agents-enterprise-data-access-2026/)) | Bounded scope pilots first; certified answer badges; show-your-work SQL transparency |
| **Scope hallucination** ("ACTUAL vs. ACTUALS" filter issue) | A wrong phase name in a filter returns 0 rows silently - the exact bug hit in OWIsMind semantic model (L058, Phase 'ACTUAL' -> 'ACTUALS') | Validate filter values against the value index before executing; already fixed in OWIsMind |
| **Governance absent from AI path** | Many orgs bolt AI on top of ungoverned data; access controls bypass expected in chat UI | Row/column security must apply identically to conversational and dashboard paths |
| **Over-promising forecasting / what-if** | Looker Code Interpreter generates Python for forecasting but results are not guardrailed by business rules | Label forecasts/what-if as "projection, not certified" and show confidence intervals |
| **Enterprise pricing gates** | Power BI Copilot requires Fabric F64+ (high cost); Cortex Analyst is pay-per-token | For OWIsMind: all inference runs inside Dataiku LLM Mesh - no external API cost surprise |

---

### BOTTOM LINE FOR OWIsMind

OWIsMind already covers the core (NL Q&A, semantic grounding, Evidence/show-work, multi-mode cost tiers). The highest-leverage gaps vs. best-in-class are:
1. **Proactive digest** - push KPI alerts to email/Slack (Tableau Pulse's biggest adoption driver)
2. **Follow-up suggestion chips** - post-answer (all leaders; zero-code UX add)
3. **"Explain this number" shortcut** - decomposition on any numeric result
4. **Shareable export** - PNG/email of a chart+narrative (exec persona requires this)
5. **Certified-answer badge** - visible trust signal on every verified answer (Qlik Answers pattern)

Sources:
- [ThoughtSpot Spotter Conversational BI - TechTarget](https://www.techtarget.com/searchbusinessanalytics/news/366615693/ThoughtSpot-AI-agent-Spotter-enables-conversational-BI)
- [ThoughtSpot Spotter Agents - TechTarget](https://www.techtarget.com/searchbusinessanalytics/news/366636078/ThoughtSpot-automates-full-platform-with-new-Spotter-agents)
- [Databricks AI/BI Genie - Zenlytic](https://zenlytic.com/blog/databricks-ai-bi-genie)
- [Snowflake Intelligence 2025 - Snowflake.help](https://snowflake.help/snowflake-intelligence-your-gateway-to-ai-driven-insights/)
- [Snowflake Cortex Analyst vs Databricks Genie - Colrows](https://colrows.com/blogs/cortex-analyst-vs-genie/)
- [Looker Conversational Analytics - Google Cloud Blog](https://cloud.google.com/blog/products/business-intelligence/a-closer-look-at-looker-conversational-analytics/)
- [Tableau Pulse Product Page - Salesforce](https://www.salesforce.com/analytics/tableau/pulse/)
- [Tableau Pulse Insight Types - Tableau Help](https://help.tableau.com/current/online/en-us/pulse_insights_platform_insight_types.htm)
- [Tableau Pulse Feature Releases - Tableau Blog](https://www.tableau.com/blog/top-new-tableau-pulse-feature-releases-know)
- [Power BI Copilot vs Amazon Q 2026 - ClickUp](https://clickup.com/blog/amazon-q-vs-copilot/)
- [Amazon QuickSight vs Power BI 2026 - EPC Group](https://www.epcgroup.net/amazon-quicksight-vs-power-bi-enterprise-comparison)
- [Hex Fall 2025 Launch - Agents for Analytics](https://hex.tech/blog/fall-2025-launch/)
- [Qlik Answers - Qlik Product Page](https://www.qlik.com/us/products/qlik-answers)
- [Qlik Agentic Experience Press Release - Qlik](https://www.qlik.com/us/news/company/press-room/press-releases/qlik-debuts-agentic-experience)
- [Building Trust in Conversational BI: Semantic Layers - AtScale](https://www.atscale.com/blog/build-trust-conversational-bi-semantic-layer/)
- [Conversational Analytics AI Agents Enterprise 2026 - Promethium](https://promethium.ai/guides/conversational-analytics-ai-agents-enterprise-data-access-2026/)
- [Qlik Answers Unstructured Data - Tech Field Day](https://techfieldday.com/2025/glean-insights-value-from-unstructured-data-with-qlik-answers/)