# Decision History

Direction: Confirmed: user decisions favor concise rationale that preserves project direction,
complete truthful end-to-end behavior, informed choices,
production-grade foundations, canonical ownership, realistic verification, and interfaces whose
visible hierarchy matches the task and promised content (D-20260714-03, D-20260713-03,
D-20260713-04, D-20260714-04, D-20260710-03, D-20260710-05). Inferred: repeated choices indicate a taste for compact low-noise UI,
stable ordering and grouping, visible exceptions, contextual actions, and durable state rather than
volatile cleverness (D-20260707-01, D-20260707-02, D-20260707-07, D-20260707-08); apply these
patterns by default while treating them as inference when a new context materially differs.

## [D-20260714-04 — Full-repo audits trace semantic implementation](DecisionDetails/D-20260714-04.md)

Decision: Full-repo audits require source-backed per-unit semantic traces and exact-once batch-to-lead
reconciliation with derived, gap-preserving results. Every verified artifact-backed audit creates a
fully reviewed external projection; applying it to the active completion ledger requires an explicit
user request or applicable project instruction and a verifier-gated plan/apply workflow.

Why: Marker scans and UI inventories can miss code that looks finished but substitutes constants,
ignores inputs, stops at plumbing, fakes success or persistence, or never registers real behavior.
Options: selected manual contract-to-outcome tracing with enforced evidence rows over expanding TODO
regexes or relying on file coverage because arbitrary domain gaps require informed judgment. Prior
attempts: the former schema failed to prove non-UI implementation review because batches could pass
with a purpose and generic no-finding note. Intent: audit actual implementation across the whole
repository, prevent omitted batch contracts or unsupported PASS claims from producing a false-clean
result, and turn only confirmed active obligations—not raw hypotheses or history—into completion
work. Revisit only if: another method proves the same semantic and ledger reconciliation coverage
with stronger recall and precision.

## [D-20260714-03 — Decision history is a compact direction index](DecisionDetails/D-20260714-03.md)

Decision: Decision history is a compact major-decision index with one direction synthesis, exactly
`Decision` and `Why` per entry, and one selectively loaded detail file per stable ID.

Why: The main history must prevent option loops and reveal durable user intent without carrying full
reports. Options: selected a compact index plus per-decision cold details over one verbose file or
deleting supporting evidence because both rationale and context efficiency matter. Prior attempts:
the 11,491-word mixed history obscured direction and caused routine context to carry implementation
and verification detail. Intent: let agents follow engineering direction, workflow expectations,
and UI taste while distinguishing confirmed choices from inference. Revisit only if: another
structure preserves the same anti-loop rationale, direction synthesis, selective loading, and
one-file-per-decision evidence boundary more clearly.

## [D-20260714-01 — Universal policy has no numeric word limit](DecisionDetails/D-20260714-01.md)

Decision: The universal policy has no numeric length ceiling; semantic, neutrality, and safety
contracts determine validity.

Why: The former ceiling compressed meaning-bearing rules. Options: selected semantic validation
without a numeric ceiling over retaining or raising an arbitrary cap because completeness and
clarity matter more than length. Prior attempts: the fixed ceiling caused awkward compression and
lost nuance. Intent: keep policy dense through relevance, not through a metric that weakens meaning.
Revisit only if: measured context costs require a targeted mechanism that preserves every necessary
rule.

## [D-20260714-02 — Completion ledger is an open-work queue](DecisionDetails/D-20260714-02.md)

Decision: The completion ledger contains only unresolved work, removes items when verified, and is
deleted when empty; version control is its default history.

Why: Retained closed rows obscured real blockers and grew routine context. Options: selected an
open-only queue over a mixed active/resolved ledger or routine completion archive because Git
already preserves history. Prior attempts: mixed storage obscured readiness and duplicated durable
evidence. Intent: make incomplete scope impossible to hide while keeping routine context focused.
Revisit only if: an explicit audit requirement cannot be met by version control or a cold archive.

## [D-20260713-01 — Visual approval remains visible across output boundaries](DecisionDetails/D-20260713-01.md)

Decision: A visual-approval pause keeps the approval state and exact requested response visible,
embedding both in the artifact when no follow-up can appear.

Why: Transient approval prompts can disappear between output surfaces. Options: selected persistent
approval state over commentary-only follow-up because the user must always see the pending choice.
Prior attempts: transient-only requests failed to remain visible with the generated artifact.
Intent: make state and next actions explicit while limiting visual exploration to genuine design
choices. Revisit only if: every producing surface guarantees a durable colocated approval request.

## [D-20260713-02 — Universal policy replaced the root-cause skill](DecisionDetails/D-20260713-02.md)

Decision: Universal policy owns the proportionate prevention-first loop for agent mistakes, and the
dedicated root-cause skill is retired.

Why: The separate workflow duplicated policy and measured report vocabulary rather than causal
truth. Options: selected one universal prevention contract over a second specialized skill because
one source reduces drift. Prior attempts: the skill duplicated requirements and its lexical verifier
caused false confidence without proving the diagnosis. Intent: learn from mistakes with the
narrowest effective guardrail and proportionate process. Revisit only if: a distinct capability
requiring executable tooling cannot live in policy, tests, or scoped verifiers.

## [D-20260713-03 — Informed choices and content-first UI are universal requirements](DecisionDetails/D-20260713-03.md)

Decision: Agents explain realistic options before requesting a choice, and destinations show the
content promised by their labels before forms or secondary material.

Why: Generic advice omitted the knowledge needed for user decisions and allowed primary content to
be buried. Options: selected explicit option context and content-first destinations over broad 'keep
prominent' guidance because the stricter contract is testable. Prior attempts: the first rewrite
missed unexplained choices, unnamed records, and lists displaced below forms. Intent: respect user
agency and favor direct, immediately legible interfaces whose hierarchy matches their labels.
Revisit only if: evidence shows an explicit destination has a different primary task or the user
chooses another hierarchy after informed comparison.

## [D-20260713-04 — Universal policy is reusable and full scope gates readiness](DecisionDetails/D-20260713-04.md)

Decision: Universal policy holds reusable principles, scoped controls hold specialized enforcement,
full requested scope gates readiness, and agent mistakes use prevention-first handling.

Why: The former policy mixed universal intent with application-specific procedure and let partial
delivery resemble completion. Options: selected a reusable core plus scoped enforcement over one
monolithic rule file because each guarantee belongs at its narrowest durable layer. Prior attempts:
the monolithic policy caused critical obligations to be hidden and allowed incomplete work to appear
ready. Intent: prefer complete, truthful, production-grade outcomes with durable learning over fast
partial claims. Revisit only if: a rule cannot be enforced or understood at its current scope.

## [D-20260712-01 — Global policy uses direct canonical links](DecisionDetails/D-20260712-01.md)

Decision: Every discovered global policy entry links directly to the canonical repository source,
while repository-root policy remains repository-specific.

Why: Independent installed policy files diverged from their source. Options: selected direct
canonical links over copied or mirrored files because ownership and updates remain unambiguous.
Prior attempts: independent copies drifted and lost stricter owner rules. Intent: maintain one
writable source of truth without erasing runtime-specific repository guidance. Revisit only if: a
runtime cannot safely consume a direct link and provides an equally verifiable synchronization
mechanism.

## [D-20260711-01 — Routine bug fixing was made direct and proportionate](DecisionDetails/D-20260711-01.md)

Decision: At that time, bounded bugs used a direct fix path and the root-cause skill was reserved
for serious cases; D-20260713-02 superseded the skill boundary while preserving proportionality.

Why: Mandatory broad diagnosis burdened simple corrections. Options: selected focused
reproduce/fix/regression handling over diagnose-only authorization and automatic postmortems because
routine work should remain proportionate. Prior attempts: requiring another authorization message
and a large report caused delay without improving isolated fixes. Intent: act autonomously on safe
in-scope corrections while scaling analysis to risk. Revisit only if: D-20260713-02 is superseded by
evidence that focused prevention cannot handle routine mistakes.

## [D-20260711-02 — Link tests distinguish owned aliases from operator paths](DecisionDetails/D-20260711-02.md)

Decision: Link tests canonicalize only their test-owned temporary root while production continues to
reject operator-supplied paths containing symlink components.

Why: Host-managed temporary aliases and operator-controlled aliases have different trust boundaries.
Options: selected narrow test-root canonicalization over canonicalizing neither or all paths because
it preserves production strictness. Prior attempts: canonicalizing neither failed on host-managed
aliases, while canonicalizing operator paths would be unsafe. Intent: adapt fixtures to the host
without weakening real safety guarantees. Revisit only if: the host no longer aliases test-owned
roots or production adopts a stronger equivalent identity check.

## [D-20260711-03 — System services use explicit verified home paths](DecisionDetails/D-20260711-03.md)

Decision: System-level service units for non-root users use explicit home paths and verify the
loaded unit before the first production start.

Why: System-manager expansion did not honor the expected user's home. Options: selected explicit
paths plus loaded-unit verification over `%h` and syntax-only checks because runtime resolution is
the real contract. Prior attempts: `%h` resolved to the root home and caused a valid-looking unit to
target the wrong state. Intent: fail closed on runtime identity and verify behavior at the
operational boundary. Revisit only if: the service manager provides a proven user-home expansion
with equivalent loaded-state verification.

## [D-20260711-04 — Product and audit ownership are split by lifecycle](DecisionDetails/D-20260711-04.md)

Decision: Runtime products and coupled deployment assets belong to an independent product
repository, while this repository owns audit skills and the shared verification harness; later
decisions reduced the canonical set to five skills.

Why: Product runtime and portable audit packages release and operate differently. Options: selected
separate repositories with explicit boundaries over one combined checkout because each can evolve
independently. Prior attempts: combined ownership impeded independent releases, and the first weaker
link journal failed to detect canonical-source replacement. Intent: make ownership, deployment, and
canonical sources explicit while preserving valuable concurrent work. Revisit only if: the
components again share one inseparable lifecycle with a verified dependency boundary.

## [D-20260711-05 — Stale and current work use a semantic merge](DecisionDetails/D-20260711-05.md)

Decision: The stale local branch and fresh remote branch were reconciled by per-feature semantic
precedence rather than choosing either tree wholesale.

Why: Both sides contained valuable non-equivalent work. Options: selected an evidence-backed
semantic merge over remote-only or local-only replacement because tree-wide precedence would discard
valid changes. Prior attempts: local-only review missed newer architecture, while wholesale
selection risked lost safety work or lost product work. Intent: preserve concurrent intent and
resolve conflicts by meaning, not timestamp or convenience. Revisit only if: one side is proven
disposable or an exact mechanical merge preserves all semantics.

## [D-20260711-06 — Repository-wide work requires fetched ancestry](DecisionDetails/D-20260711-06.md)

Decision: Broad repository work classifies fetched remote ancestry first, preserving stale dirty
work and reconciling it from an isolated current checkout.

Why: Local cleanliness does not prove a current baseline. Options: selected fetched ancestry
classification over local-only inspection because remote truth is required before broad conclusions.
Prior attempts: a comprehensive local audit passed but missed newer remote architecture. Intent:
ground repository-wide decisions in current evidence without discarding valuable dirty work. Revisit
only if: the repository has no remote authority or the user explicitly establishes an offline
baseline.

## [D-20260710-01 — Runtime actions preflight dependencies and bind binaries](DecisionDetails/D-20260710-01.md)

Decision: GUI mutations perform deterministic dependency preflight, and delivered binaries are
cryptographically bound to their source inputs.

Why: Failure must occur before destructive partial action, and source completion is not binary
delivery. Options: selected full preflight and source/binary provenance over bare executable lookup
and unbound builds because the user experiences the running artifact. Prior attempts: bare lookup
caused partial shutdown before failure, while an older binary diverged from newer source. Intent:
make operational actions atomic and delivery evidence end to end. Revisit only if: the runtime
provides an equivalent transactional dependency and provenance mechanism.

## [D-20260710-02 — Skills install through transactional canonical links](DecisionDetails/D-20260710-02.md)

Decision: Repository-owned skills install as direct canonical links through a transactional plan,
apply, verify, and rollback workflow.

Why: Installed copies obscure ownership and can change independently. Options: selected direct
identity-verified links over copies or chained links because canonical bytes and rollback remain
provable. Prior attempts: copied directories and chained links drifted after deployment and hid
which source was authoritative. Intent: preserve one writable skill source while making mutations
recoverable and exact. Revisit only if: a runtime cannot use links and offers content-addressed
installation with equivalent drift and rollback guarantees.

## [D-20260710-03 — Runtime and interface contracts are truthful and fail closed](DecisionDetails/D-20260710-03.md)

Decision: Skills, backups, runtime state, and interfaces expose only guarantees supported by real
state and deterministic evidence, failing closed when prerequisites are absent.

Why: Advertised capability without end-to-end proof creates unsafe trust. Options: selected explicit
prerequisites and evidence-bound claims over optimistic defaults because unverified success is worse
than visible unavailability. Prior attempts: stronger advertised claims than their proof created
unsafe concurrency and provenance risk. Intent: make every control, status, and guarantee truthful
to the underlying system. Revisit only if: new evidence proves a broader claim across realistic
success and failure paths.

## [D-20260710-04 — Approved hierarchy and exact structured starts are required](DecisionDetails/D-20260710-04.md)

Decision: The approved resource-first hierarchy is used, and exact-lease starts send structured
executable arguments with the exact lease identifier.

Why: Visual hierarchy and command identity are user-visible contracts. Options: selected the
approved grouping and structured arguments over inferred layout and raw command strings because both
preserve exact intent. Prior attempts: the raw-command path was rejected and could not preserve
argument boundaries safely. Intent: follow approved UI structure precisely and keep actions bound to
the object they affect. Revisit only if: the user approves another hierarchy or the protocol gains
an equally safe structured representation.

## [D-20260710-05 — Visual evidence is production-view and source-bound](DecisionDetails/D-20260710-05.md)

Decision: Canonical visual evidence renders the production interface and binds both artifact bytes
and exact renderer-source bytes.

Why: An image hash proves bytes, not that those bytes represent current production UI. Options:
selected production rendering plus source hashes over a separate snapshot shell or PNG-only
provenance because evidence must track the delivered interface. Prior attempts: snapshot-only shells
drifted and PNG-only hashes allowed stale visuals to remain valid. Intent: prefer evidence that
proves both what users see and which source produced it. Revisit only if: another mechanism binds
equivalent production behavior and source identity.

## [D-20260710-06 — Actions carry attribution and conflict by target domain](DecisionDetails/D-20260710-06.md)

Decision: Lease actions carry exact actor and project attribution, and concurrent operations
conflict by stable target domain rather than action name.

Why: Ownership and concurrency safety span the whole lifecycle. Options: selected full attribution
and target-wide exclusion over partial payloads and action-name locks because all mutations of one
target can conflict. Prior attempts: a malformed release omitted mandatory ownership fields, while
action-name-only locking allowed unsafe overlap. Intent: keep destructive and lifecycle actions
explicitly attributable, isolated, and recoverable. Revisit only if: the protocol removes
attribution or proves finer conflict domains safe.

## [D-20260710-07 — Native validation uses its purpose-built workflow](DecisionDetails/D-20260710-07.md)

Decision: Native build, test, packaging, launch, and UI validation use the dedicated workflow and
remain pending when that workflow is unavailable.

Why: Static inspection cannot substitute for compiled native behavior, and direct desktop control
can interfere with the user. Options: selected the purpose-built workflow over ad hoc control or
structural-only claims because it owns the real safety boundary. Prior attempts: static-only
validation was inadequate and direct interaction carried user-session risk. Intent: report native
evidence honestly and avoid commandeering the user's environment. Revisit only if: another workflow
proves equivalent build, runtime, packaging, and interaction safety.

## [D-20260707-01 — UI uses a compact exception header and stable action slots](DecisionDetails/D-20260707-01.md)

Decision: The console uses fixed action slots with uniform color semantics and a compact header that
surfaces only states needing attention.

Why: Routine state should not crowd navigation or make controls jump. Options: selected stable slots
and exception-only status over conditional buttons and always-on chips because alignment and signal
matter more than decorative status. Prior attempts: conditional controls caused misalignment, while
constant chips caused noise and displaced useful header space. Intent: favor compact, calm UI with
stable geometry, consistent action meaning, and visible exceptions. Revisit only if: user testing
shows another layout improves scanability without movement or noise.

## [D-20260707-02 — Persistent lists never sort by volatile metrics](DecisionDetails/D-20260707-02.md)

Decision: Persistent collections use stable semantic ordering and never use live metrics as implicit
sort keys.

Why: Volatile values should inform a row, not move it. Options: selected semantic stable order over
CPU-based order because users build spatial memory and need predictable targets. Prior attempts: CPU
sorting caused rows to jump on every poll and broke the unrequested stability expectation. Intent:
prefer calm, predictable interfaces over clever dynamic behavior. Revisit only if: the user
explicitly requests a transient metric-ranked view distinct from the persistent list.

## [D-20260707-03 — Container-hosted web servers are first-class servers](DecisionDetails/D-20260707-03.md)

Decision: Web-serving containers use durable container identity and container-side ports as first-
class routing targets.

Why: Host-published ports are transport details and can change. Options: selected durable container
identity over host-port identity because routing must survive restarts without cross-wiring. Prior
attempts: host-port identity drifted, and accepting incompatible address families could not
guarantee proxy reachability. Intent: model operational objects by stable domain identity rather
than incidental runtime coordinates. Revisit only if: the container platform provides another
durable routable identity with equivalent reachability checks.

## [D-20260707-04 — CI uses fast-bind HTTP fixtures](DecisionDetails/D-20260707-04.md)

Decision: CI code uses a fast-bind server or plain TCP fixture rather than constructing stock
standard-library HTTP servers directly.

Why: Reverse-DNS work during bind can stall CI before readiness logic begins. Options: selected
fast-bind fixtures over stock server construction or longer timeouts because the cause is binding
behavior, not readiness duration. Prior attempts: both the bare command and an embedded threaded
server stalled on the target CI host. Intent: remove environmental nondeterminism at its source
rather than masking it with timeouts. Revisit only if: the standard server proves nonblocking bind
behavior on every supported runner.

## [D-20260707-05 — Validation anchors executable semantics and call sites](DecisionDetails/D-20260707-05.md)

Decision: Static validation pins executable behavior and its wired call sites, backed by behavioral
fixtures, rather than comments or definitions alone.

Why: Text presence does not prove execution. Options: selected semantic call-site checks plus
behavior over broad substring needles because the latter can stay green after functionality
disappears. Prior attempts: comment, syntax, and unwired-definition needles missed removed behavior
and produced false passes. Intent: make validation claims correspond to real reachable behavior.
Revisit only if: a stronger parser or runtime test fully replaces the static contract.

## [D-20260707-06 — UI grouping consumes authoritative membership](DecisionDetails/D-20260707-06.md)

Decision: The Board consumes coordinator-issued project membership instead of deriving membership
from names or filesystem guesses.

Why: Display and action authority must agree. Options: selected coordinator membership over client
heuristics because the control plane already owns the truth. Prior attempts: client-side guesses
caused resources to appear under projects whose actions did not own them. Intent: keep interfaces
consistent with authoritative domain ownership and avoid synthetic categorization. Revisit only if:
membership ownership moves to a new authoritative service used by both display and actions.

## [D-20260707-07 — One membership model drives grouping and actions](DecisionDetails/D-20260707-07.md)

Decision: Display grouping and whole-project actions use one authoritative container-attribution
model.

Why: Two definitions of membership create contradictory UI and operations. Options: selected one
shared model over separate display and action inference because users expect a group and its action
target to be identical. Prior attempts: independent attribution paths diverged for explicit,
missing, and ambiguous membership. Intent: make visual grouping a truthful preview of operational
scope. Revisit only if: a deliberate product distinction between display and action membership is
specified and visible.

## [D-20260707-08 — The interface is project-centric and preference updates are deltas](DecisionDetails/D-20260707-08.md)

Decision: The console uses a project tree, authoritative membership, and server-merged hide or
reveal deltas that automatically reveal active items.

Why: Navigation, grouping, and preferences must preserve operational context. Options: selected
project-centric hierarchy and delta updates over flat/client-guessed grouping and whole-list
replacement because authority and concurrent edits stay consistent. Prior attempts: guessed grouping
diverged, and whole-list writes lost updates during polls, retries, and multiple clients. Intent:
favor clear hierarchy, durable user preferences, and safety-driven self-revelation over hidden
active state. Revisit only if: user research supports another hierarchy and its persistence model
handles concurrency equivalently.

## [D-20260706-01 — Port assignments are durable and explicit](DecisionDetails/D-20260706-01.md)

Decision: Stable per-server ports use a separate durable assignment map and require explicit
unassignment before reuse.

Why: Lease lifecycle and identity lifecycle are not the same. Options: selected a durable assignment
map over lease-bound ports or never-expiring leases because legitimate lease cleanup must not change
server identity. Prior attempts: lease reclamation caused port reuse risk and would reintroduce
drift. Intent: preserve stable externally visible identity across routine lifecycle events. Revisit
only if: the platform supplies an equally durable identity-to-port registry.

## [D-20260706-02 — Operations use paged navigation and bounded transient metrics](DecisionDetails/D-20260706-02.md)

Decision: The console uses paged navigation, bounded in-memory metric history, and direct lease-
management surfaces.

Why: One long page did not scale, while transient charts did not justify durable storage complexity.
Options: selected pages and bounded memory over a single page and disk-backed metrics because
navigation stays legible without inventing a retention subsystem. Prior attempts: the single long
page did not work as feature density grew. Intent: keep operational UI structured, responsive, and
focused on immediate decisions. Revisit only if: long-term analysis becomes a stated requirement
with a defined retention model.

## [D-20260706-03 — Live deployment features use real integrations](DecisionDetails/D-20260706-03.md)

Decision: Authentication, container availability, per-server subdomains, and transport security were
delivered as real operational integrations rather than placeholders.

Why: The requested live system needed end-to-end behavior across unrelated deployment surfaces.
Options: selected real integrated capabilities over mocks or deferred plumbing because production
controls must perform their claims. Prior attempts: placeholder-only or partially wired behavior was
inadequate for the live deployment goal. Intent: finish real data, security, routing, and failure
paths before calling a feature ready. Revisit only if: deployment scope explicitly removes one of
these capabilities or transfers its ownership.

## [D-20260705-01 — Wildcard renewal is unattended DNS automation](DecisionDetails/D-20260705-01.md)

Decision: Wildcard certificate renewal uses registrar-API DNS-01 hooks with confined credentials and
unattended operation.

Why: Wildcard coverage and reliable renewal both matter. Options: selected automated DNS-01 over
manual DNS-01 or HTTP-01 because only it provides wildcard issuance without recurring operator
action. Prior attempts: manual renewal caused standing outage risk, and HTTP-01 could not issue
wildcard coverage. Intent: make production security maintenance automatic, least-privileged, and
observable. Revisit only if: the registrar API becomes unavailable and another automated DNS
authority provides equivalent controls.

## [D-20260705-02 — Wildcard issuance initially used manual DNS-01](DecisionDetails/D-20260705-02.md)

Decision: Wildcard issuance initially used a blocking manual DNS-01 workflow and was superseded by
D-20260705-01 once API automation became available.

Why: Wildcard hosts could not be covered by the existing challenge. Options: selected manual DNS-01
over HTTP-01 while API credentials were unavailable because it was the only viable wildcard path.
Prior attempts: HTTP-01 could not issue a wildcard, while manual renewal later caused recurring
outage risk. Intent: preserve secure coverage while making temporary operational compromises
explicit and replaceable. Revisit only if: automated DNS is unavailable and the user accepts the
documented manual renewal burden.

## [D-20260705-03 — Named-host issuance initially used in-process HTTP-01](DecisionDetails/D-20260705-03.md)

Decision: The service initially handled ACME HTTP-01 in-process to issue named-host certificates
without downtime; D-20260705-02 and D-20260705-01 superseded it for wildcard coverage.

Why: DNS credentials were unavailable and stopping the service was unacceptable. Options: selected
in-process HTTP-01 over standalone downtime or unavailable DNS automation because it could issue the
known host safely. Prior attempts: named-host HTTP-01 could not cover arbitrary subdomains and
therefore failed the wildcard requirement. Intent: preserve availability while evolving temporary
certificate paths toward complete automation. Revisit only if: only fixed hostnames are required and
HTTP-01 has an operational advantage over DNS automation.

## [D-20260705-04 — The web edge delegates operational truth](DecisionDetails/D-20260705-04.md)

Decision: A minimal web edge terminates TLS, routes subdomains, authenticates users, and delegates
operational state and mutations to the coordinator.

Why: One control plane should own lifecycle truth. Options: selected a zero-third-party-dependency
edge with coordinator delegation over direct shelling or duplicated lifecycle logic because
divergence and public-edge supply-chain risk stay lower. Prior attempts: none known. Intent: keep
the public surface small, secure, and truthful to one operational authority. Revisit only if: a
maintained framework or new control plane provides a demonstrably safer full lifecycle.

## [D-20260705-05 — The Board refreshes only when useful](DecisionDetails/D-20260705-05.md)

Decision: The renamed Board refreshes only while visible, coalesces work, and publishes inventory
only when it changes.

Why: Background activity should correspond to user-visible value. Options: selected visibility-
gated, change-driven refresh over constant polling because hidden identical work wastes resources.
Prior attempts: continuous polling caused idle CPU use, repeated identical publication, and
redundant regrouping. Intent: prefer efficient, quiet software whose background cost is justified by
visible behavior. Revisit only if: hidden refresh is required for an explicit alerting or automation
contract.

## [D-20260703-01 — Hardening targets functional contracts](DecisionDetails/D-20260703-01.md)

Decision: Repository hardening corrects executable verifier, harness, runtime, backup, and CI
behavior rather than treating documentation changes as completion.

Why: A broad audit exposed multiple independent functional gaps. Options: selected end-to-end
corrections and regression fixtures over documentation-only updates because advertised behavior must
be real. Prior attempts: structural checks missed broken integration and created false confidence.
Intent: make audits and skills prove usable outcomes, not merely polished contracts. Revisit only
if: this aggregate record is split into narrower major decisions without losing its evidence links.

## [D-20260703-02 — Detector tests prove realistic recall and precision](DecisionDetails/D-20260703-02.md)

Decision: Detector self-tests use independent realistic must-catch failures and intentional-pattern
precision controls for every advertised class.

Why: A detector and fixtures can agree while both model the wrong failure. Options: selected
independent realistic fixtures over detector-shaped synthetic tests because recall must be
demonstrated against how applications actually break. Prior attempts: the first synthetic suite
missed ten of eleven realistic defects and produced false confidence. Intent: treat a green verifier
as evidence only when its test failures are independent and representative. Revisit only if: a
stronger empirical benchmark replaces the fixture contract without reducing precision controls.

## [D-20260702-01 — Dual runtimes initially used mirrored policy](DecisionDetails/D-20260702-01.md)

Decision: Both agent runtimes initially received mirrored skills and policy while sharing machine
state; D-20260710-02 and D-20260712-01 superseded mirrors with direct canonical links.

Why: Shared resources required behavioral parity across runtimes. Options: selected mirrored
installation over divergent runtime rules as the available initial mechanism. Prior attempts:
mirrored copies later drifted and obscured the writable source. Intent: keep agent behavior
consistent across runtimes while moving toward one canonical source. Revisit only if: direct links
are unavailable and a content-addressed synchronization mechanism proves equivalent.

## [D-20260702-02 — Resource telemetry follows process trees](DecisionDetails/D-20260702-02.md)

Decision: Resource telemetry aggregates process-tree use per server and project instead of observing
launcher processes alone.

Why: The process consuming resources is often a descendant rather than the launcher. Options:
selected process-tree aggregation over launcher-only measurement because it follows real ownership.
Prior attempts: launcher-only telemetry was inadequate when child processes owned listeners and
resource use. Intent: report operational data by domain meaning rather than convenient but
misleading process handles. Revisit only if: the runtime provides authoritative cgroup or container
accounting with better ownership fidelity.

## [D-20260702-03 — Rendered web UI receives deterministic verification](DecisionDetails/D-20260702-03.md)

Decision: Rendered web interfaces receive deterministic browser-side geometry and visibility
verification in addition to visual review.

Why: Screenshots and model judgment do not reliably catch measurable layout failures. Options:
selected browser-side heuristics plus review over screenshot-only review because geometry, clipping,
occlusion, and target coverage are software-detectable. Prior attempts: screenshot review missed
hidden, off-canvas, clipped, and invisible content. Intent: combine human design judgment with
deterministic evidence for functional UI quality. Revisit only if: another renderer-level method
proves equal recall and precision across supported states.
