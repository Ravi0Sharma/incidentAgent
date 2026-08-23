# Målmiljö och prioritering av testdata

Status: CloudWatch bekräftad men parkerad; workload/deploykälla beslutsgate  
Senast granskad: 2026-08-09

## Beslut

Nya loggkorpora ska inte prioriteras för att de finns tillgängliga. De ska
prioriteras efter hur väl de motsvarar den miljö som Incident Agent faktiskt
ska analysera.

Spark-adaptern behålls som ett godkänt parser-, sampling- och grupperingsprov,
men fortsatt Spark-specifik utveckling är parkerad. Hadoop, HDFS, BGL och
OpenStack är också evalkorpora; ett godkänt test innebär inte att de systemen
ingår i produktens supportgräns.

## Vad repot faktiskt bekräftar

| Område | Nuvarande evidens | Slutsats |
| --- | --- | --- |
| Aktiv release | Local-Safe v0.1 med fixtures/replay | Ingen produktionsmiljö är ansluten |
| Avsedd alertkälla | Amazon CloudWatch Alarm via EventBridge | Lokal, allowlistad state-change-adapter finns; autentiserad transport till webhook är ännu inte vald |
| Logggränssnitt | CloudWatch Logs Insights | Read-only-adapter och lokalt kontrakt finns; verkliga log groups och AWS-sandboxprov saknas |
| Mätetal | CloudWatch GetMetricData | Read-only-adapter och lokalt kontrakt finns; verkliga namespaces/dimensions och AWS-sandboxprov saknas |
| Agentens tillstånd | MySQL | Detta beskriver agentens egen lagring, inte nödvändigtvis systemen den övervakar |
| Workloads | `payments`, `checkout`, `auth`, `catalog`, `search`, batch | Demonstrationskatalog; inte ratificerad produktionskatalog |
| Orkestrering | Kubernetes-fält kan normaliseras | Ingen Kubernetes-connector eller bekräftad Kubernetes-målmiljö |
| Kafka | Förväntad framtida relevans enligt projektägaren | Medvetet parkerad tills grundpipelinen och målmiljön är tydliga |
| Spark/Hadoop | Offentliga evaldataset och adapters | Ingen evidens att de är vanliga i den avsedda miljön |
| Hosting | Railway senare | Fortsatt sista steg |

## Information som måste fastställas

Följande är `unknown` tills det fylls med verkliga miljöbeslut:

- vilka applikationer och bakgrundsjobb som ska omfattas först;
- språk och ramverk, exempelvis Java/Spring, Python, Node eller Go;
- om workloads körs på VM, Docker, Kubernetes, serverless eller en blandning;
- verkliga CloudWatch log groups, metric namespaces/dimensions, AWS account och region;
- vilken deployment/config-källa som är riktig;
- primära databaser, cacher, externa API:er och senare meddelandebussar;
- vanligaste incidentklasserna och vilka utfall som kan användas som facit;
- faktisk loggform: JSON, logfmt, text, multiline-stacktraces och fältnamn;
- tenant-, region-, cluster-, namespace- och servicegränser.

## Dataprioritet tills miljöprofilen är klar

| Prioritet | Datatyp | Varför |
| --- | --- | --- |
| P0 | Ett verkligt eller godkänt replay-fönster från den avsedda applikationsstacken | Validerar parser, service/entity, tidslinje, signal och impact i rätt domän |
| P0 | Samma incident med alert, relevanta loggar och observerat utfall | Ger starkare sanning än fristående ERROR-rader |
| P1 | Vanliga applikationsfel: timeout/refused, dependency-fel, databas/pool och process crash/restart | Matchar en generell servicebaserad incidentagent |
| P1 villkorad | Container-/Kubernetes-event | Endast om målmiljön använder dem |
| P2 villkorad | Kafka broker-, producer-, consumer- och lag-signaler | När Kafka tas in i supportgränsen |
| Parkerad | Spark-specifika executor-, stage- och shufflefall | Endast om Spark finns i verklig support scope |
| Parkerad | Fler Hadoop/HDFS-varianter | Nuvarande korpora har redan gett generell pipelineevidens |
| Låg | OpenSSH/säkerhetsloggar | Annan produktdomän om säkerhetsincidenter inte ingår |

## Minsta krav på nästa dataset

Nästa case ska helst innehålla:

1. ett definierat incidentfönster och en tydlig tidszon eller deklarerad
   source-relative ordering;
2. service, execution/workload eller annan entity som kan korreleras;
3. minst en observerad signal och ett separat observerat utfall;
4. normalt brus från samma miljö;
5. facit eller reviewdata som hålls utanför pipelinen;
6. källproveniens, tillåten användning och en lokal checksumma;
7. tillräckligt med rader för att mäta vad samplingen tappar.

Om datasetet endast har fristående INFO/ERROR-rader utan incidentgräns,
entity och utfall får det användas för parser/gruppering, men inte styra
ytterligare incidentlogik eller OpenAI-utvärdering.

## Nästa arbetsordning

1. Fyll en privat kopia av `config/cloudwatch_sources.example.yaml` med en
   enda verklig service, dess alarm, log groups och tre relevanta metrics.
2. Ge runtime-rollen minsta read-only-rättigheter och kör ett AWS-sandboxprov.
3. Välj en enda vanlig incidentklass från miljön.
4. Skaffa ett minimerat replay-fönster med signal, brus och utfall.
5. Kör parser → sampling → grouping → timeline → evidence pack utan LLM.
6. Rätta bara generella och domänrelevanta signalförluster.
7. Kör OpenAI först när evidenspacken innehåller något modellen faktiskt
   kan tolka och svaret kan bedömas mot ett utfall.
