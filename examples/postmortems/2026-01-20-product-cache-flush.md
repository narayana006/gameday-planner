# Catalog errors after product-cache was flushed

Date: 2026-01-20
Severity: SEV2
Duration: 25 minutes

## Summary

A configuration rollout restarted every product-cache node at once and the
cache was flushed. catalog-api fell through to catalog-db for every request.
The single database instance could not keep up with the cold cache and
storefront-web product pages failed until the cache refilled.

## Root cause

All cache nodes restarted together, and catalog-db has no capacity headroom for
a cold cache.

## Action items

- Roll cache restarts one node at a time.
- Load test catalog-db with an empty cache.
