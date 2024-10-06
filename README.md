# Trixel Management Service

The *Trixel-Management-Service* (TMS) handles participating measurement stations and ensures location and data-privacy.
The TMS server registers itself at the provided Trixel-Lookup-Service (TLS) and manages all delegated trixels.
Measurement stations, which are located within one of the trixels delegated to a TMS can communicate their measurements to that TMS.
If enough participants are present within a trixel and data quality can be ensured, the TMS will publish anonymized environmental observations for that trixel.

## Development

This project is built on FAST-API and Sqlalchemy. For local development of the TMS, the use of an SQLite database is sufficient.
Use `fastapi run src/trixelmanagementserver.py --port <port-nr>` during development.
The client module can be generated with the help of the [generate_client.py](client_generator/generate_client.py) which is also used during continuous deployment.

[Pre-commit](https://pre-commit.com/) is used to enforce code-formatting, formatting tools are mentioned [here](.pre-commit-config.yaml).
[pytest](https://pytest.org/) is used for testing.

## Running the TMS (configuration options)

During startup the TMS loads a local configuration file from `config/config.toml`.
Such a config file may look like the following development-configuration.

```toml
log_level = "DEBUG"
trixel_update_frequency = 15

[tls_config]
host = "tls.home.fleisch.dev"

[tms_config]
host = "tms.home.fleisch.dev"

[privatizer_config]
privatizer = "naive_average"
logging = true

[tms_config.database]
use_sqlite = true
```

General configuration options are detailed [here](src/config_schema.py), while privatizer-specific configuration options and their descriptions are located [here](src/privatizer/config_schema.py)

* `log_level`, int: Logging level which is used for the TMS
* `trixel_update_frequency`, Time: Time (by default in seconds) between privatizer evaluations
* `sensor_data_purge_interval`, Time: Time period between sensor recording purges (Default to `1` Hour)
* `sensor_data_keep_interval`, Time: Time period of retained sensor measurements (Default to `2` Weeks)

### `tls_config`

Trixel Lookup Server configuration.

* `host`, string, required: Address of the TLS at which this TMS should register
* `use_ssl`, bool: Determines if `https` is used while communicating with the TMS (Default to `true`)

### `tms_config`

Trixel management server specific options.

* `host`, str: The address under which this TMS will be accessible. Shared with contributing measurement stations via the TLS.
* `id`, int: ID of this TMS at the TLS. Automatically populated once registered at the TLS.
* `active`, bool: Determines if this TMS is currently active. May be changed automatically by the TLS.
* `api_token`, SecretStr: Authentication token which is used at the TLS. Automatically populated once registered at the TLS.

### `tms_config.database`

TMS Database configuration options.

* `custom_url`, Optional[str]: Custom database address which can be used to directly configure SQLAlchemy. Mutually exclusive with all other options, except `use_sqlite`.
* `dialect`, Optional[str]: Dialect which is used by SQLAlchemy.
* `user`, Optional[str]: DB-Username which is used by SQLAlchemy.
* `password`, Optional[SecretStr]: DB-Password which is used by SQLAlchemy.
* `host`, Optional[str]: Address of the DB which is used by SQLAlchemy.
* `port`, Optional[int]: Port which is used by SQLAlchemy.
* `db_name`, Optional[str]: Name of the DB which is used by SQLAlchemy.
* `use_sqlite`, bool: Set to true when using an SQLite database. Defaults to `false`.

### `privatizer_config`

* `privatizer` determines which privatizer is used by the TMS. One of `blank`,`latest`,`naive_average`,`naive_smoothing_average`,`average`,`smoothing_average`,`naive_kalman`,`kalman`.

See [here](src/privatizer/config_schema.py) for more details regarding their specific options and usage.

## Deployment

The continuous deployment pipeline generates [docker images](https://hub.docker.com/r/tillfleisch/trixelmanagementserver/tags) which can be used for deployment of the TMS.
Use `docker run` or a compose-file like this to run the TMS.
Make sure to mount your TMS-config file to `/config` within the container.

```yaml
services:
  trixelmanagementserver:
    image: tillfleisch/trixelmanagementserver:latest
    ports:
      - 4666:80
    volumes:
      - ./tms_config:/config
```
