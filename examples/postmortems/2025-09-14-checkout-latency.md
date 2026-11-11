# Checkout slowdown during payments-provider latency

Date: 2025-09-14
Severity: SEV2
Duration: 47 minutes

## Summary

The payments-provider API started responding in 6 to 8 seconds instead of 300 ms.
checkout-api had no timeout on that call, so request threads piled up until the
service stopped answering health checks. storefront-web showed errors on the
cart page for about a third of shoppers.

## Root cause

No client timeout and no circuit breaker on the call from checkout-api to
payments-provider. Latency in the provider turned into thread exhaustion in
checkout-api.

## Action items

- Add a 2 second timeout and a circuit breaker to the payments client.
- Alert on thread pool usage above 80%.
