# Shadow-readiness audit 2026-08-14

## Beslut

**No-go för produktionstelemetri i dag.** Projektet är en verifierad lokal
incidentanalysprototyp, men saknar fortfarande drift- och miljöbevis som krävs
för en säker read-only shadow. Det får köras med fixtures/replay och utan
externa effekter. `ENVIRONMENT=shadow` ska inte sättas i en publik miljö förrän
förkraven nedan är stängda.

## Verifierat i denna audit

- Python 3.11.15 och den hash-låsta utvecklingsmiljön är installerade.
- Lokal MySQL 8.4 är nåbar och `/readyz` rapporterar databas, kö och schema som
  ready.
- `scripts/quality_gate.py` passerar med 291/291 tester, Ruff, scoped mypy,
  compileall, promptbudget och repository secret scan.
- Branch coverage är 74,5 procent för hela repot, 82,2 procent för kärnscopet
  och 97,2 procent för säkerhetskontrollerna.
- En syntetisk Alertmanager-payload går via HTTP-intag, MySQL event-before-ack,
  lease-jobb och analys till `awaiting_analysis_review`. Identisk replay blir
  `duplicate_event`.
- Ett tidigare otestat E2E-fel hittades: Alertmanager-tider med millisekunder
  och `Z` gav MySQL-fel 1292 och HTTP 500. Intaget normaliserar nu accepterade
  ISO-8601-tider till UTC `DATETIME`; ett regressionstest täcker både `Z` och
  offset.
- `PUBLISH_EXTERNAL=false`, `SKIP_LLM=true`, lokala mock-connectors och ingen
  Phoenix-export användes. Ingen produktionstelemetri eller extern destination
  anropades.
- Docker finns inte på auditmaskinen, så containerbygget är inte verifierat.

## Omfattning och kvarvarande mängd

Den auktoritativa readiness-listan innehåller 232 primärkrav: 70 stängda och
162 öppna. Av de öppna är 87 markerade P0. Detta beskriver full
produktionsreadiness, inte mängden kod som saknas och inte den kortaste vägen
till en begränsad shadow.

För en första shadow ska scopet begränsas till en tjänst, ett AWS-konto/en
region, en alarmfamilj, CloudWatch Logs, tre ratificerade metrics, en riktig
deploy/config-källa, read-only åtkomst och inga externa writes. Följande tio
leveranspaket återstår före och under en sådan körning:

1. Ratificera supportmatris, service-ID:n, incidentvolym, dataägare,
   retention och fail-open/fail-closed-policy.
2. Fyll en privat CloudWatch source map och bevisa IAM least privilege i ett
   AWS-sandboxkonto, inklusive riktig alarmtransport och deploykälla.
3. Slutför canonical evidence/revision-flödet för riktiga connectorresultat,
   UTC/originaltid, recursive redaction, datakvalitet och provenance.
   Den lokala kod- och persistensdelen är verifierad i
   `ARCVIAL_SHADOW_PACKAGE_3_2026-08-14.md`; samma canary måste passera mot den
   riktiga Arcvial-loggkällan innan produktionsdata godkänns.
4. Den lokala delen för separat API/kontinuerlig worker, heartbeat/lease
   renewal, incidentlås, graceful shutdown, backpressure och crash recovery är
   verifierad i `ARCVIAL_SHADOW_PACKAGE_4_2026-08-14.md`. Samma process- och
   restartprov måste fortfarande passera i en multi-service stagingmiljö.
5. Inför versionsstyrda DB-migrationer, begränsade runtime-roller,
   connection pooling samt verifierad backup/restore.
6. Registrera riktig OIDC, prova RBAC/CSRF/tenantgränser, använd secret manager,
   TLS/at-rest-kryptering och godkänd egresslista.
7. Lås container/build, kör som non-root, separera staging/shadow-konfiguration,
   lägg till CI/CD, rollback och oberoende kill-switchar för intake, worker,
   connectors, modell och publicering.
8. Exportera redigerade strukturerade loggar/metrics/traces till ett gemensamt
   backend; bygg dashboard, backlog/failure-alerts och syntetisk canary.
9. Kör stagingprov för E2E, dubbel leverans, samtidighet, timeouts, provider- och
   connectorfel, restart, last och minst ett restore-drill.
10. Skapa ett miljömatchat gold/replay-set och ratificera gränser för citation,
    unsupported claims, abstention, top-3-nytta, latens och kostnad. Kör därefter
    minst 50 representativa incidenter eller 14 stabila shadow-dagar med noll
    externa effekter.

## Rekommenderad exekveringsordning

1. Beslut och en-service-scope (paket 1–2).
2. Kodens runtime-säkerhet (paket 3–5).
3. Identitet, deploy och observability (paket 6–8).
4. Staging/failure-bevis (paket 9).
5. Shadow-trial och kvalitetsbeslut (paket 10).

Railway kan vara hosting för API/worker, men nuvarande `Dockerfile` installerar
från det olåsta `requirements.txt`, kör som root och startar bara API:t.
Nuvarande `railway.toml` beskriver endast en API-service. Detta är blockerare,
inte kosmetik.

## Externa beslut och åtkomst som krävs

- första riktiga service, AWS account/region och CloudWatch
  alarm/log groups/metrics;
- den verkliga deploy/config-källan;
- AWS sandbox och en definierad read-only IAM-roll;
- OIDC-provider, roller och callback-domän;
- hostingval, staging/shadow-databas, secret manager, backupmål och
  observability-backend;
- godkänd modell/provider, dataregion/retention och kostnadstak;
- en namngiven serviceägare, SRE-granskare, säkerhetsgranskare och driftägare.

Utan dessa uppgifter går det att fortsätta härda och testa repot lokalt, men
det går inte att sanningsenligt godkänna eller starta en produktion-shadow.
