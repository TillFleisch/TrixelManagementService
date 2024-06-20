# Trixel Management Service

The *Trixel-Management-Service* (TMS) handles participating measurement stations and ensures location and data-privacy.
The TMS server registers itself at the provided Trixel-Lookup-Service (TLS) and manages all delegated trixels.
Measurement stations, which are located within one of the trixels delegated to a TMS can communicate their measurements to that TMS.
If enough participants are present within a trixel and data quality can be ensured, the TMS will publish anonymized environmental observations for that trixel.
