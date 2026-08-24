# Parkerat arbete och återupptagningsgrindar

Senast uppdaterad: 2026-08-09  
Aktivt mål: **Local-Safe v0.1 genom review**

Detta är projektets samlade register över sådant vi medvetet väntar med. Det är
inte en extra arbetskö: aktiv ordning och progress finns i
[`PROJECT_MASTER_CHECKLIST.md`](PROJECT_MASTER_CHECKLIST.md). En punkt flyttas
dit först när dess återupptagningsvillkor är uppfyllt.

## Säkerhetsblockerare – får inte behandlas som vanlig parkering

- [ ] **Spärra den exponerade OpenAI API-nyckeln och kontrollera Usage.**
      Nyckelvärdet ska inte kopieras till dokument, tester eller loggar. Skapa
      därefter en ersättningsnyckel med minsta nödvändiga behörighet och
      kostnadsgräns. `.env` är git-ignorerad, men det gör inte en redan visad
      nyckel säker igen. **Återuppta före:** nästa verkliga OpenAI-anrop,
      staging eller deployment. Detta blockerar inte lokala tester med stubbar
      eller helt mockade provideranrop.

## Drift, hosting och verkliga datakällor

- [ ] **Verklig SSO/OIDC-konfiguration.** Den providerneutrala
      sessions-/JWT-/RBAC-koden finns lokalt. Registrering av callback,
      claims-to-role-mappning, allowlist och staging-E2E väntar tills IdP och
      driftmiljö är valda.
      **Återuppta vid:** `M15` eller när stagingmiljön bestäms.
- [ ] **CloudWatch som faktisk källkedja.** Adapter och lokala kontrakt finns,
      men verkliga AWS-konton, regioner, IAM-policy, log groups, metrics,
      service-routing och sandbox-E2E väntar. Loki/Prometheus och replay är
      lokala standardkällor under tiden. **Återuppta vid:** `M09`–`M10`, när
      målmiljön och read-only AWS-åtkomst är kända.
- [ ] **Kafka/streaming-ingest.** Bygg inte connector, consumer groups,
      offset/replay-policy eller backpressure enbart för att Kafka kan förekomma
      senare. **Återuppta vid:** `M10`/`M17`, bara om den faktiska miljön använder
      Kafka och dess eventkontrakt är tillgängligt.
- [ ] **Produktionspersistens och operativ drift.** Managed MySQL,
      objektlagring, backup/restore, workers, köer, observability, IaC, canary,
      rollback och soak/chaos väntar på staging. **Återuppta vid:** `M16`–`M20`.

## Data, regler och utvärdering som kräver verklig miljö

- [ ] **Service-specifika rule packs.** Skapa inte regler för att passa Hadoop,
      HDFS eller andra publika dataset. **Återuppta vid:** `M09`–`M12`, när
      faktiska tjänster, beroenden, ägare och vanliga incidenttyper är kända.
- [ ] **Representativt privat gold set.** Bygg detta från miljömatchade
      incidenter eller anonymiserade replays, inte från ett publikt corpus.
      **Återuppta vid:** `M11`, med dubbel mänsklig bedömning.
- [ ] **Historiska/peer-baselines och confidence-kalibrering.** Vänta tills
      tillräckligt många representativa, granskade fall finns. **Återuppta vid:**
      `M12`; jämför då också mot en enkel baseline utan LLM.
- [ ] **Rootly Apache/OpenSSH-corpora.** Lägg endast till dem om webbserver- eller
      SSH-signaler motsvarar målmiljön. **Återuppta vid:** beslut i `M09`.
- [ ] **SREGym eller annan agentisk benchmark.** Kör som isolerad spike först
      efter att statiska kontrakt och egen fault injection har en stabil
      baseline. **Återuppta efter:** `M11`–`M12`.

## Efter review

- [ ] **Strikt RCA-kontrakt.** Typat output-schema, claim-level grounding,
      motsägelser och ärlig abstention ska byggas från exakt godkänd revision.
      **Återuppta efter:** stabil pre-review- och reviewkedja (`M01`–`M05`).
- [ ] **Postmortem-kvalitetskontrakt.** Fakta, hypoteser och okänt ska skiljas,
      och alla sakpåståenden ska citeras. Visuell finputsning är inte grinden.
      **Återuppta vid:** `M06`.
- [ ] **Historiskt review-minne.** Retrieval får bara använda godkända eller
      kurerade poster med proveniens, behörighet, expiry och rättningsflöde.
      **Återuppta vid:** `M14`, efter att nyttan kan mätas.
- [ ] **Extern publicering av postmortem.** Kräver separat approval av exakt
      draft, audit och idempotent outbox med partial-failure recovery.
      **Återuppta vid:** `M21`.
- [ ] **Remediation, restart, rollback och load mirroring.** Behåll endast
      evidensbaserade read-only-förslag. Ingen exekvering utan separat scope,
      approval, timeout, verifieringssteg, rollback-plan och audit trail.
      **Återuppta först efter:** kontrollerad pilot och uttryckligt produktbeslut.

## Tester som medvetet inte är aktiva just nu

- [ ] **GitHub-repository och verklig GitHub Actions-körning.** Workflowen
      finns, men repo-initiering, remote, push och bevis från en ren Linux-
      checkout väntar. **Återuppta när:** projektet ska versionshanteras eller
      delas via GitHub. Detta blockerar inte den lokala kvalitetsgrinden eller
      arbetet mot 80/90-procentsmålen.
- [ ] **Breddad OpenAI/provider-felmatris.** Connection refused, DNS, timeout,
      401/403, 429, circuit open, tom usage och incidentdeadline finns samlade i
      [`DEFERRED_CONNECTION_FAILURE_TESTS.md`](DEFERRED_CONNECTION_FAILURE_TESTS.md).
      **Återuppta före:** Shadow eller hostad deployment. Bounded retry/deadline och lokal
      fail-closed-logik fortsätter vara aktiva krav.
- [ ] **Staging-load, fairness, crash, migration, restore och minst 24 h soak.**
      Dessa kräver en representativ deployad miljö. **Återuppta vid:**
      `M16`–`M20`.

## Fortsatt aktivt – inte parkerat

Följande ska alltså inte flyttas hit eller glömmas:

- [x] Slutför `M07`: adversarial payloads, malformed/oversized input,
      redaction, lokal dependency scan och säker secret-scan utan att läsa
      ignorerade hemlighetsfiler.
- [x] Kör om hela regressionssviten efter Linux/syslog-ändringarna: 284/284
      passerar i den synkade, hash-låsta miljön.
- [x] Slutför den lokala coverage-delen av `M08`: relevant kärnpipeline mäter
      82,4 procent mot grinden 80 och säkerhetskritisk kod mäter 97,2 procent
      mot grinden 90. Hela repositoryt mäter 74,8 procent med ratchet på 74.
      Verklig GitHub Actions-körning är parkerad ovan.
- [ ] Fortsätt därefter enligt `M09` endast när målmiljö eller nödvändig input
      faktiskt finns.

## Regel för att återuppta en parkerad punkt

En punkt återupptas bara när angivet villkor är uppfyllt. Då ska den:

1. få ett konkret acceptanskriterium och ansvarig milstolpe i masterchecklistan;
2. kopplas till relevanta krav-ID:n i `PRODUCTION_READINESS.md`;
3. verifieras på data och miljö som motsvarar den avsedda användningen;
4. lämnas okryssad här tills verifieringsbeviset finns.
