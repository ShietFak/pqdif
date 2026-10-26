# Security

This initial alpha parses binary input under configurable resource limits. Use
limits appropriate for your workload and keep the package updated. Complete-file
buffering, decoded trees and expanded numeric arrays all consume memory; limits
are ceilings, not a promise of a particular peak process-memory budget.

For suspected security vulnerabilities, use the repository's private vulnerability
reporting facility if enabled. Otherwise open an issue describing the impact and
request a private contact channel before sharing exploit details. For non-sensitive
bugs, a minimized synthetic file and expected behavior are useful.
