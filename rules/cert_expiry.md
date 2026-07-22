---
id: cert-expiry
title: TLS certificate expired or invalid
level: critical
category: config_change
tags:
  - tls
  - cert
selection:
  message_regex: "certificate (has expired|is not yet valid|verify failed)|x509:|SSL_ERROR_BAD_CERT"
condition: selection
runbook: https://runbooks.example.com/tls
---

# TLS certificate expired or invalid

A TLS certificate is invalid. Check cert-manager status and certificate expiry
dashboards. This usually needs manual intervention (renew or rotate).
