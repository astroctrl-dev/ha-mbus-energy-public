FROM python:3.12-alpine
RUN apk add --no-cache tzdata && pip install --no-cache-dir pyserial==3.5 paho-mqtt==2.1.0 openpyxl==3.1.5
COPY raw_telegram_log.py i18n.py ui_translations.py temperature_units.py maintenance_schedule.py bus_timing.py mbus_probe.py mbus_records.py ha_measurements.py mqtt_bridge.py mbus_service.py poll_schedule.py meter_registry.py meter_discovery.py meter_ui.py monthly_diagnostic.py analysis_export.py history_model.py rolling_history.py history_controller.py clock_model.py clock_maintenance.py /opt/
WORKDIR /opt
CMD ["python3", "/opt/mbus_service.py"]
