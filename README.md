# Enoe-Report — Ficha trimestral del mercado laboral de Jalisco

Genera automáticamente la ficha informativa trimestral de la **ENOE (INEGI)** para Jalisco:
tasa de desocupación, participación económica, informalidad y subocupación, con comparativo
nacional, posición entre las 32 entidades, comparativo regional y **desagregación por sexo**.

- **Robot**: el día que INEGI publica (06:00 CDMX) descarga los microdatos, genera la ficha
  (`.txt` y `.docx`), la manda por correo y la guarda en `fichas/`.
- **Dashboard** (Streamlit): series históricas, indicadores por sexo, descarga de fichas y botón
  para generarlas a mano.

| Documento | Para quién |
|---|---|
| [GUIA.md](GUIA.md) | Usuarios: qué hace, cómo generar la ficha a mano, metodología |
| [ROBOT.md](ROBOT.md) | Administrador: GitHub Actions, correo, despliegue del dashboard |

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

*Proyecto de Aplicación Profesional — Economía, ITESO · Datos: INEGI, ENOE*
