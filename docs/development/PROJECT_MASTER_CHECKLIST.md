# Projektets masterchecklista

Senast inventerad: 2026-08-24

Aktivt mål: **Local-Safe v0.1**  
Auktoritativ kravlista: [`PRODUCTION_READINESS.md`](../operations/PRODUCTION_READINESS.md)

Medvetet uppskjutna punkter och deras återupptagningsvillkor finns samlade i
[`DEFERRED_WORK_CHECKLIST.md`](DEFERRED_WORK_CHECKLIST.md). Den filen är ett
parkeringsregister; den här filen är fortfarande den enda aktiva arbetskön.

Det här dokumentet är projektets enda arbetskö. Det ersätter inte
acceptanskriterierna i `PRODUCTION_READINESS.md`, utan grupperar dem i en ordning
som går att genomföra och bocka av. Ingen hostad deployment är aktiv just nu.

## Hur mycket återstår?

| Mått | Klart | Öppet | Totalt |
| --- | ---: | ---: | ---: |
| Alla checkboxrader i readiness-dokumentet | 199 | 192 | 391 |
| Primära krav med stabilt ID | 72 | **160** | 232 |
| Dubblettfria Shadow/Pilot/GA-grindar | 0 | 32 | 32 |

Den råa checklistan är alltså 50,9 procent ikryssad. Bara 31,0 procent av de
primära produktionskraven är formellt stängda. Det betyder inte att 69,0 procent
av koden saknas: flera öppna produktionskrav har redan en fungerande lokal del,
men saknar exempelvis verklig målmiljö, lastprov, säkerhetsbeslut eller
driftbevis. Det sanningsenliga återstående talet är **160 primärkrav**, samlade i
arbetsbatcherna nedan. De 32 releasegrindarna räknas inte en gång till.

## Regler för att bocka av

- Bocka av en arbetsbatch här först när dess exit-kriterium och länkade
  primärkrav är verifierade.
- Bocka samtidigt av respektive ID i `PRODUCTION_READINESS.md` och länka
  test/resultat där. En lokal demo stänger inte ett produktionskrav.
- Ett avsiktligt uppskjutet arbete är fortfarande `[ ]`, inte `[x]`.
- Börja inte nästa fas om den förutsätter ett ännu öppet beslut eller bevis i
  föregående fas.
- Postmortem, minne, extern publicering, remediation, Kafka och hostad deployment får inte
  dra fokus från den aktiva pre-review-pipelinen.

## Redan verifierad grund

Detta är befintlig grund, inte påståenden om production readiness.

- [x] Label-last ingest, gruppering, timeline och evidenspaket körs mot Hadoop,
      HDFS_v1 och OpenStack utan att facit läcker in i modellen.
- [x] Typade observationer, impact-policy, kandidater, grounding och ärlig
      abstention är implementerade.
- [x] Review-gaten delar beslutslogik mellan API och HTML; supported review kan
      godkännas och abstention kan inte godkännas.
- [x] Review-HTML visar analys och begränsad timeline före beslut samt tekniska
      detaljer bakom en expanderbar sektion.
- [x] Blindade OpenAI-prov har verifierat transport, structured output,
      grounding och säker final boundary på de dokumenterade fallen.
- [x] Den daterade liveportföljen i `OPENAI_LIVE_EVALUATION_2026-08-09.md`
      verifierar 22/22 provideranrop, sju HDFS/BGL/ZooKeeper-statusgränser och
      två fulla pre-review-fall. Ett synligt observation-pattern-ID saknades i
      Hadoop-validatorns allowlist; den generella kontraktsbuggen är rättad och
      det exakta fallet passerar omtest.
- [x] Extern publicering är avstängd som standard och nuvarande körläge är
      fixture/replay-only.
- [x] Promptbudgetkontrollen passerar; postmortem-prompten är 3 743 tecken mot
      taket 6 000.
- [x] Senaste lokala regression är 352/352 tester och review-
      scenarierna är 3/3. Ett explicit OpenAI-test med 100 000 syntetiska
      webhookhändelser och två workers gav 12 analysjobb/revisioner, 12
      lyckade provideranrop och 0 dead letters; incidentbudget spärrade 6
      senare anrop till deterministisk fallback.

## Fas 0 – stäng nuvarande lokala milstolpe

- [x] **M00 – Local-Safe closure record.** Kör om den kanoniska sviten mot
      disponibel MySQL, bekräfta `PUBLISH_EXTERNAL=false`, samla datum,
      miljö/version, resultat, kända begränsningar och ansvarig återstartsägare
      i en closure-fil. Exit: alla fem punkter i `SAFE_COMPLETION_PLAN.md` har
      daterat bevis och beslutet säger uttryckligen “inte Shadow/production”.
      Tekniskt bevis och stängningsbeslut finns i
      den aktuella evidensuppdateringen i
      [`LOCAL_SAFE_CLOSURE_2026-08-24.md`](../reports/LOCAL_SAFE_CLOSURE_2026-08-24.md)
      och den konsoliderade [`EVALUATION.md`](../EVALUATION.md).

## Fas 1 – förbättra pipelinen fram till och med review

Detta är nästa aktiva genomförandefas. Arbeta uppifrån och ned.

- [ ] **M01 – Kanonisk incidentrevision.** Nya connector-observationer appendas
      utan att skriva över gammal evidens; update, resolve, duplicate, reopen,
      reprocess och samtidiga händelser får deterministiskt utfall. Exit:
      lifecycle-, update- och concurrency-E2E passerar. Krav: `ING-010`,
      `ING-015`, `ING-018`, `EVD-011`, `EVD-018`, `COR-014`, `TST-006`–`TST-008`.
      Lokal progress: append-only evidensversioner, supersession, maskinläsbar
      revisionsdiff, resolve/reopen, out-of-order worker completion och fyra
      samtidiga revisionsskrivare passerar. Staging load/fairness, CORS/CSRF och
      verklig connector-E2E återstår innan batchen kan stängas.
- [ ] **M02 – Evidensens datakvalitet och proveniens.** Stabil evidence-ID,
      rekonstruktionsbar query, recursive redaction i alla sinks, truncation-
      metadata, freshness/completeness och tydlig untrusted-data-gräns. Exit:
      ett sparat paket kan rekonstrueras och inga fixtures/secrets läcker.
      Krav: `EVD-009`, `EVD-010`, `EVD-013`–`EVD-015`, `EVD-019`, `EVD-020`,
      `SEC-005`, `SEC-006`.
      Lokal progress: hash och exakt revisionsmedlemskap valideras fail-closed;
      kontrollerad DB-manipulation blockerar approval men tillåter rejection.
      Varje revision bär också stabila innehållshashar för regler,
      normalisering, suppressions, code map, service registry och evidence pack.
      Alla connectorrader redigeras nu före checkpointad graph-state. Alert,
      grupperad logg, metric och deploy lagras i samma canonical envelope med
      UTC/originaltid, lineage, klassificering och dubbla integritetskontroller.
      En sanerad HTTP/MySQL-canary gav noll råa canaryträffar och 7/7 giltiga
      evidensrader. Samma prov måste upprepas mot varje godkänd verklig
      loggkälla innan shadow-trafik tillåts.
- [ ] **M03 – Korrelation och oberoende grounding.** Slutlig typad hypotesmodell,
      mekanism, stöd, motsägelser, entity/tid-relationer, reranking och
      fail-closed citation validation. Exit: inga okända eller rollfelaktiga
      evidence-ID:n kan nå review. Krav: `COR-007`–`COR-010`, `COR-013`,
      `COR-015`–`COR-017`, `EVD-012`.
      Lokal progress: pre-review-valideringen skiljer nu cause, mechanism,
      impact, contradiction, outcome, recovery och successful completion.
      Kända men rollfelaktiga ID:n tas bort även från blast radius och next
      steps. Review-sidan visar nu en begränsad, escaped diff för tillagd,
      korrigerad och borttagen evidens samt kandidatens rank/confidence/score-
      ändring. En positiv read-only-policy stoppar okända/muterande steg och
      falska executed-action-claims; senaste 352/352 regressionstester passerar.
      RCA/postmortem-grounding och service-specifika rule-packbeslut återstår
      innan batchen kan stängas. Rule packs är uttryckligen parkerade tills
      faktiska tjänster, ägare och vanligaste incidenttyper är kända; generiska
      miljöantaganden ska inte byggas för att passa LogHub-data.
- [ ] **M04 – LLM-kontrakt och hårda budgetar.** Structured output, retry endast
      inom incidentdeadline, kooperativ cancellation, tool/context/token/cost-
      tak och full call ledger. Exit: deadline- och budgettester visar att inga
      nya anrop startas efter stoppgränsen. Krav: `LLM-007`–`LLM-011`,
      `LLM-013`, `PERF-005`, `PERF-006`, `REL-007`, `REL-008`.
      Lokal progress: varje faktiskt providerförsök, inklusive retry, går nu
      genom en incidentgemensam preflight för call-, input-, output-, total-
      och USD-budget. Lyckade och misslyckade försök samt blockerade anrop
      sparas utan promptinnehåll med stage, provider, modell, request-ID,
      parametrar, token usage/reservation, latens, finish-/stopporsak och kostnad.
      Budgetgränser och återstående budget visas i review; shadow/production
      vägrar starta utan positiv USD-gräns och tokenpriser. Ett 100 000-event
      test med två workers och verkliga OpenAI-anrop konvergerade till 12
      revisioner och 12 lyckade provideranrop utan dead letters; 6 senare
      anrop blockerades av incidentbudgeten. Senaste 352/352 tester och
      promptbudgetkontrollen passerar. Strict RCA/postmortem-output,
      kooperativ cancellation och bred prompt-injection-corpus återstår.
- [ ] **M05 – Reviewrevision och audit.** Servern avvisar stale, obehörig eller
      osparad revision; diff mellan revisioner visas och alla beslut har actor,
      tid, reason och immutable historik. Exit: approve/reject/request-more-
      evidence/stale-revision fungerar i API och HTML. Krav: `REV-006`–`REV-014`,
      `OBS-009`, `SEC-011`.
      Lokal progress: approve, reject och request-more-evidence är nu separata
      beslut i graph, API, båda HTML-vyerna och MySQL-ledgern. Mer evidens kräver
      konkret feedback och går genom samma begränsade återundersökningsloop.
      Sparad kandidat/evidens, revision diff, local reviewer identity, rationale,
      request-ID och stale/unsaved revision är testade. MySQL låser pending-
      revisionen så ett konkurrerande beslut avvisas medan en identisk retry är
      idempotent. Provider-neutral OIDC stöder authorization-code-session för
      webbläsare och signerade Bearer tokens för API-klienter. Viewer, decision
      och operator har separata roller; review-POST kräver en tidsbegränsad CSRF-
      token bunden till incident och pseudonymiserad identitet. Verklig IdP-
      registrering och staging-E2E återstår.
- [ ] **M06 – Postmortem quality contract, inte visuell finputsning.** Utkastet
      byggs från exakt godkänd analysrevision, skiljer fakta/hypotes/okänt,
      citerar kända ID:n och faller tillbaka till ett ärligt internt utkast.
      Exit: positiva, negativa och hallucinerande model-outputfall passerar.
      Krav: `REV-015`, `REV-016`, `REV-019`, `LLM-012`.
- [x] **M07 – Lokal adversarial- och säkerhetsgate.** Prompt injection i loggar,
      malformed/oversized payloads, CSRF/session, path traversal, secret scan,
      dependency scan och felvägsredaction testas. Exit: fail-closed utan
      känsligt läckage. Krav: `SEC-007`, `SEC-014`, `SEC-015`, `TST-010`,
      `TST-014`.
      Lokalt bevis: promptgränser kan inte stängas av evidens, tool-policy
      blockerar okända verktyg/argument/URL:er, regex-sökning är literal,
      komprimerade loggar har hårda expansionsgränser, HTML/path/redirect/CSRF
      failar säkert och tool/publisher/report-sinks redigerar secrets. Den
      värdesuppressande repository-scannern passerar utan att läsa `.env`;
      hash-låset ger giltig CycloneDX-SBOM och dagens `pip-audit` rapporterar
      inga kända sårbarheter. Den låsta fullsviten passerar 352/352.
- [ ] **M08 – Reproducerbar CI-kvalitetsgate.** Lint, typer, enhet/integration,
      coverage-trösklar, promptbudget, säkerhetsskanning och reproducerbara
      beroenden körs automatiskt. Exit: en ren checkout ger samma gröna gate.
      Krav: `TST-004`, `TST-005`, `DEP-003`, `DOC-005`.
      Lokal progress: Python 3.11.15, hash-låsta direct/transitive dependencies,
      Ruff, avgränsad mypy, compileall, promptbudget, secret scan, full MySQL-
      suite, branch coverage, dependency audit och SBOM är samlade i
      `scripts/quality_gate.py` och `.github/workflows/quality.yml`. Låst lokal
      körning är grön med 352/352 tester. Hela repositoryt mäter 75,4 procent
      och har en 74-procentsratchet; kärnscopet mäter 82,2 procent mot grinden
      80 och säkerhetskontrollerna 95,9 procent mot grinden 90. Coverage-delen
      av `M08` är därmed stängd. En faktisk ren GitHub Actions-körning återstår
      men är medvetet parkerad i `DEFERRED_WORK_CHECKLIST.md`.

## Fas 2 – välj målmiljö och skaffa rätt evaldata

Starta denna fas när den faktiska systemmiljön och datakällorna är kända.

- [ ] **M09 – Support- och säkerhetsmatris.** Bestäm stödda alerttyper,
      servicegränser, severity/SLO-policy och vad systemet uttryckligen inte
      får göra. Krav: `SCP-003`, `SCP-006`–`SCP-008`,
      `DOC-008`, `DOC-010`.
- [ ] **M10 – Första verkliga read-only-källkedjan.** Implementera endast de
      miljömatchade logg-, metric- och deploy/config-källorna, med pagination,
      rate limit, schema drift och freshness. Kafka
      väntar tills målmiljön kräver det. Krav: `SRC-006`–`SRC-016`, `TST-015`.
      Lokal progress: CloudWatch Alarm-state translator, Logs Insights och
      GetMetricData är implementerade bakom en versionerad service-allowlist.
      Okänd service/alarm avvisas före AWS-anrop; polling och pagination är
      begränsade och partial/truncation bevaras i proveniens. Verkliga AWS-
      credentials/log groups/metrics, sandbox-E2E och deploykälla återstår, så
      batchen är fortfarande öppen. Spåret är parkerat enligt
      projektbeslut och de lokala standardkällorna är fortsatt Loki/Prometheus.
- [ ] **M11 – Märkt gold set och evaluator.** Minst 100 representativa incidenter
      eller godkända replays med dubbel SRE-bedömning, disagreement och
      regressionsversionering. Publica dataset kompletterar men ersätter inte
      miljömatchad data. Krav: `TST-011`–`TST-013`.
- [ ] **M12 – Kalibrering och baselines.** Kalibrera confidence/abstention,
      mät precision/recall/false positives och jämför mot enkel baseline utan
      LLM. Exit: releasegränser är ratificerade före modelltrimning. Krav:
      `COR-011`, `COR-012`, `EVD-016`, `EVD-017`, `PERF-004`.
- [ ] **M13 – Provider-, modell- och kostpolicy.** Godkänd dataregion/retention,
      primär modell, fallback, version pinning, canary/eval vid byte och faktisk
      token/kostnadsbokföring. Krav: `LLM-014`–`LLM-018`, `PERF-008`, `PERF-012`.
- [ ] **M14 – Mät minne innan det byggs ut.** Besluta om cross-incident memory
      ger mätbar nytta; bygg därefter curated/filter-first retrieval med
      provenance, auth, expiry, correction/deletion och eval. Krav:
      `MEM-003`–`MEM-015`.

## Fas 3 – staging, drift och externa effekter

- [ ] **M15 – Identitet, privacy och secrets.** SSO/RBAC, tenantgräns,
      retention/deletion/legal hold, encryption, secret manager, egress och
      säkerhets-/privacygranskning. Krav: `SEC-008`–`SEC-010`, `SEC-012`,
      `SEC-013`, `SEC-016`–`SEC-018`.
- [ ] **M16 – Produktionspersistens och recovery.** Migrationer, pooling,
      backup/restore, corruption/failover och objektlagring för stora artefakter.
      Exit: dokumenterade restore- och crash-drills. Krav: `REL-003`–`REL-006`,
      `REL-009`–`REL-011`, `REL-015`–`REL-017`.
- [ ] **M17 – Oberoende workers och backpressure.** Separata workers,
      heartbeats, leases, fair queueing, circuit breakers, bounded retries och
      overload-degradation. Krav: `REL-012`–`REL-014`, `PERF-009`–`PERF-011`.
      Lokal progress: API-drain kan stängas av, en separat kontinuerlig worker
      publicerar durable liveness, förnyar jobb- och incidentlease, dränerar på
      signal och återtar utgångna jobb. Gemensamt kötak omfattar alert,
      reprocess och dead-letter replay. Direkt process-/SQL-bevis finns i
      process-/SQL-testerna och operator-runbooken. Ett separat 100 000-event
      OpenAI-test bekräftar att 5-minuters incidentbucketing bevarar alla
      händelser men begränsar arbetet till 12 revisioner/provideranrop.
      Multi-host staging, SLO-baserad last, fairness, circuit breakers och
      overload-observability återstår.
- [ ] **M18 – Operativ observability.** End-to-end context, strukturerade
      redigerade loggar, metrics/traces, SLO-dashboard, alerts, canary och
      skyddad auditåtkomst. Krav: `OBS-003`–`OBS-008`, `OBS-010`–`OBS-012`.
- [ ] **M19 – Reproducerbar staging/deploy.** Container/build lock,
      config/secrets per miljö, IaC, migration jobs, CI/CD, health/readiness
      och kill switches. Ett driftmål väljs först här om det fortfarande är
      nödvändigt. Krav: `DEP-004`–`DEP-010`, `DEP-012`–`DEP-014`.
- [ ] **M20 – Last, soak, chaos och kapacitet.** Verifiera stora payloads,
      burst, connector/model/database-fel, återstart och minst 24 h soak mot
      SLO/kostnad. Krav: `TST-009`, `TST-016`–`TST-019`.
      Lokal progress: 100 000 syntetiska, signerade webhookhändelser genom hela
      API-/tvåworker-/OpenAI-pipelinen gav 12 revisioner, 12 lyckade
      provideranrop och 0 dead letters. Det saknar ratificerad kapacitet,
      30-procentig headroom, soak och målmiljöfel, och stänger därför inte
      kapacitetskraven.
- [ ] **M21 – Exakt publiceringsapproval och outbox.** Ett postmortem får lämna
      systemet först efter separat exact-draft approval, auth/audit och
      idempotent outbox med partial-failure recovery. Ingen automatisk
      remediation ingår. Krav: `REV-017`, `REV-018`.
- [ ] **M22 – Dokumentation och governance.** ADR:er, runbooks,
      reviewerhandbok, data inventory, doc checks, review/expiry och release-
      manifest hålls aktuella. Krav: `DOC-002`–`DOC-004`, `DOC-006`, `DOC-007`,
      `DOC-009`, `TST-020`.

## Fas 4 – releasegrindar

De här grindarna bockas av genom bevis från batcherna ovan; de är inte extra
implementationer och räknas därför inte in i de 160 primärkraven.

- [ ] **M23 – Shadow-Ready-förkrav.** Alla P0-krav för säker read-only shadow,
      review, data, drift och eval har bevis.
- [ ] **M24 – Shadowkörning.** Minst 50 representativa incidenter under minst
      14 dagar; noll externa effekter och ratificerade kvalitets-/latensgränser.
- [ ] **M25 – Kontrollerad pilot.** Begränsade tenants/team, reviewer game day,
      kill switches och dokumenterad release evidence.
- [ ] **M26 – GA.** Alla P0/P1-gates, säkerhet/privacy, kapacitet, restore,
      support och governance är stängda. Deployment är då en
      driftimplementation, inte ett experiment för att avgöra om pipelinen
      fungerar.

## Öppna primärkrav per område

Detta index gör att inget tappas när arbetsbatcherna används. Detaljerade
acceptanskriterier finns bara i `PRODUCTION_READINESS.md`.

| Område | Klart | Öppet | Öppna ID:n |
| --- | ---: | ---: | --- |
| 1 Scope/safety | 2 | 4 | `SCP-003`, `SCP-006`–`SCP-008` |
| 2 Intake/lifecycle | 15 | 3 | `ING-010`, `ING-015`, `ING-018` |
| 3 Connectors | 6 | 10 | `SRC-006`–`SRC-008`, `SRC-010`–`SRC-016` |
| 4 Evidence/timeline | 8 | 12 | `EVD-009`–`EVD-020` |
| 5 Correlation/hypotheses | 6 | 11 | `COR-007`–`COR-017` |
| 6 LLM boundary | 6 | 12 | `LLM-007`–`LLM-018` |
| 7 Memory | 2 | 13 | `MEM-003`–`MEM-015` |
| 8 Review/postmortem | 7 | 12 | `REV-006`–`REV-019` |
| 9 Security/privacy | 4 | 14 | `SEC-005`–`SEC-018` |
| 10 Reliability/recovery | 2 | 15 | `REL-003`–`REL-017` |
| 11 Observability/audit | 2 | 10 | `OBS-003`–`OBS-012` |
| 12 Tests/evaluation | 4 | 16 | `TST-004`, `TST-006`–`TST-020` |
| 13 Performance/cost | 4 | 8 | `PERF-004`–`PERF-006`, `PERF-008`–`PERF-012` |
| 14 Deploy/operations | 3 | 11 | `DEP-003`–`DEP-010`, `DEP-012`–`DEP-014` |
| 15 Docs/governance | 1 | 9 | `DOC-002`–`DOC-010` |
| **Totalt** | **72** | **160** | **232 primärkrav** |

## Nästa konkreta arbetsordning

1. `M00` är stängd med ett färskt Local-Safe-bevis.
2. Fortsätt `M01`–`M05` för den faktiska pre-review-kedjan.
3. Lägg till `M06` som ett litet kontraktstestat postmortem-steg; vänta med
   design/finputsning och extern publicering.
4. Stäng `M07`–`M08` innan mer verklig data ansluts.
5. Be om mer/miljömatchad loggdata först i `M09`–`M12`.
6. Bygg inte Kafka, större memory, remediation eller hostad deployment innan respektive
   senare gate faktiskt kräver det.
