# Stremio for Kodi Premium

Stremio for Kodi is an open-source Kodi client. Its core Stremio browsing, account and playback experience remains available without Premium.

Premium adds optional services that require private server-side infrastructure. Premium authority, customer records, payment state, provider credentials and entitlement grants are never stored or trusted in the public Kodi client.

## Free

The public client continues to provide the core Stremio for Kodi experience, including:

- Stremio account sign-in
- Home and account catalogs
- Continue Watching and Library
- Discover, seasons and episodes
- Installed Stremio add-ons
- Stream selection and Kodi playback
- Subtitle support
- Built-in IMDb trailer support
- TV/remote-friendly Nimbus interface

Free functionality is designed to continue working even if the MKGA Premium service is unavailable.

## Premium

Premium is reserved for optional server-backed features. The first server-gated Premium capability is **AI Translation**.

Premium features are granted only after the private MKGA backend verifies the current entitlement. The public Kodi client cannot grant Premium to itself, choose a product or price, report a payment as successful, or supply its own customer identity.

Additional Premium capabilities may be added as the project develops. Features will only be listed here once they are actually available or clearly identified as planned.

## Identity and security

Kodi does not require a separate MKGA login.

Stremio for Kodi uses the existing Stremio session to establish a short-lived MKGA session. The private backend verifies the Stremio session and derives the customer identity server-side. Premium API calls then use the short-lived MKGA token.

The client never treats a client-supplied UID, local boolean or settings value as proof of Premium entitlement.

Provider API keys, payment credentials, customer records and other private service secrets remain server-side.

## Getting Premium

Stremio for Kodi includes a bounded **Get Premium** handoff. When available, the client requests a customer-bound purchase session from the MKGA backend and displays the returned **mkga.tv** checkout link as a QR code.

Pricing, products, payment confirmation and entitlement grants are controlled by the private backend rather than the Kodi client.

## Open-source boundary

The Kodi client remains public and auditable. Features whose full implementation is already local and public cannot be meaningfully protected by a local Premium switch, so they remain free.

Premium is therefore intended for capabilities that genuinely depend on private server-side services rather than artificial client-side locks.

For installation, screenshots and general project documentation, see the [main README](README.md).

For Kodi-specific discussion and support, visit the [Stremio for Kodi thread on the Kodi Community Forum](https://forum.kodi.tv/showthread.php?tid=388819).
