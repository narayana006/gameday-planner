# Orders database failover took 11 minutes

Date: 2025-11-02
Severity: SEV1
Duration: 11 minutes

## Summary

The orders-db primary lost its host during routine maintenance. Automatic
failover started, but promotion of the replica was delayed because replication
lag was 4 minutes. checkout-api returned errors for all order writes until a
replica was promoted by hand.

## Root cause

Replication lag alerts were silenced the week before. The failover procedure had
never been exercised under lag.

## Action items

- Re-enable the replication lag alert.
- Practise failover quarterly.
