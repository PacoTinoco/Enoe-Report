# Guía del administrador — Robot y dashboard ENOE Jalisco

Dos piezas viven en este repositorio:

- **El robot** (`.github/workflows/robot.yml`): corre todos los días a las **06:00 (CDMX)** en
  GitHub Actions. Cuando INEGI publica la ENOE trimestral, genera la ficha, la manda por correo y
  la guarda en `fichas/`.
- **El dashboard** (`app.py`): publicado en Streamlit Community Cloud. Muestra la ficha, las
  series y los indicadores por sexo, y tiene un botón para correr el robot a mano.

Los usuarios de INEGI **no necesitan saber usar GitHub**: reciben el correo y entran al dashboard
con un link. Esta guía es para quien administra el repositorio.

---

## Cómo trabaja el robot

1. Lee el calendario oficial de INEGI y avisa si cambió alguna fecha.
2. Si ya salió el trimestre pendiente, genera la ficha, la manda por correo y la guarda.
3. El día de publicación revisa cada 5 minutos hasta que salen los microdatos (normalmente a las
   06:00 en punto). Si a las 10:00 no han salido, la ejecución termina en error y GitHub avisa por
   correo al administrador.
4. Aunque INEGI mueva una fecha, el robot revisa diario si ya salió el trimestre pendiente, así que
   a más tardar lo detecta a la mañana siguiente.

---

## 1. Cuenta de correo del proyecto

1. Crear una cuenta de Gmail para el proyecto (ej. `ficha.enoe.jalisco@gmail.com`).
2. Activar la **verificación en dos pasos**.
3. Crear una **contraseña de aplicación** en https://myaccount.google.com/apppasswords
   (16 letras; se usa en lugar de la contraseña normal).
4. Pedir a los destinatarios que agreguen esta cuenta a sus remitentes seguros.

## 2. Subir el código a GitHub

El repositorio debe ser **privado**: en los públicos GitHub desactiva los flujos programados tras
60 días sin actividad, y entre publicaciones pasan ~90.

En una terminal dentro de la carpeta del repositorio, primero mover `robot.yml` a su lugar
(GitHub solo lo reconoce dentro de `.github/workflows/`) y después subir todo:

```bash
mkdir .github\workflows
move robot.yml .github\workflows\robot.yml
git add .
git commit -m "Pipeline, robot y dashboard ENOE Jalisco"
git push
```

`config.ini`, `.streamlit/secrets.toml` y los ZIP de microdatos no se suben (`.gitignore`).

## 3. Secretos del robot (datos del correo)

En GitHub, en el repositorio: **Settings → Secrets and variables → Actions → New repository secret**

| Nombre | Valor |
|---|---|
| `SMTP_USUARIO` | la cuenta de Gmail del proyecto |
| `SMTP_PASSWORD` | la contraseña de aplicación |
| `DESTINATARIOS` | correos separados por coma |
| `SMTP_REMITENTE` | *(opcional)* ej. `Ficha ENOE Jalisco <ficha.enoe.jalisco@gmail.com>` |

## 4. Probar el robot

**Actions → Robot ENOE Jalisco → Run workflow**, con trimestre `2026_T2` y
"Rehacer aunque ya exista" ✔. En ~2 minutos debe llegar el correo con la ficha. A partir de ahí
corre solo todos los días.

## 5. Dashboard en Streamlit Community Cloud

**a) Token para el botón "Generar ficha".** El dashboard necesita permiso para disparar el robot.
En GitHub: foto de perfil → **Settings → Developer settings → Personal access tokens →
Fine-grained tokens → Generate new token**:

- Nombre: `streamlit-enoe`
- Expiración: la máxima disponible (anotar la fecha para renovarlo)
- Repository access: **Only select repositories** → `Enoe-Report`
- Permissions → Repository permissions → **Actions: Read and write**

Copiar el token (empieza con `github_pat_`); GitHub no lo vuelve a mostrar.

**b) Publicar la app.** En https://share.streamlit.io → **Create app → Deploy a public app from
GitHub** (o "from repository"):

- Repository: `PacoTinoco/Enoe-Report` · Branch: `main` · Main file path: `app.py`
- **Advanced settings** → Python 3.12 y en **Secrets** pegar:

```toml
[github]
token = "github_pat_..."
repo = "PacoTinoco/Enoe-Report"

[app]
clave = "una-clave-para-el-boton"
```

La `clave` es opcional: si existe, el botón "Generar ficha" la pide. Conviene ponerla si la app
es pública.

**c) Compartir.** Como el repositorio es privado, la app nace privada (Community Cloud permite
una app privada por cuenta). En la app: **Share → Invite viewers** y agregar los correos de INEGI;
les llega una invitación y entran con Google o con un link por correo. También se puede hacer
pública (los datos de la ENOE son públicos); en ese caso deja la `clave` puesta.

**d) Actualizaciones.** Cada vez que el robot guarda una ficha nueva en `main`, la app se
actualiza sola en uno o dos minutos.

---

## Mantenimiento

- **Trabaja solo en la carpeta del repositorio** y haz `git pull` antes de cambiar algo: el robot
  sube commits a `main` cada vez que genera una ficha.
- **Avisos de error del robot**: GitHub manda correo a quien modificó por última vez el flujo
  cuando una ejecución programada falla. Detalle en la pestaña **Actions**.
- **Token vencido**: si el botón del dashboard marca error 401, generar un token nuevo (paso 5a) y
  actualizarlo en la app → **Settings → Secrets**.
- **Costo**: gratis. El repositorio privado incluye 2,000 minutos de Actions al mes; el robot usa
  ~1 minuto diario, más unos minutos el día de publicación.
- **Al terminar el PAP**: transferir el repositorio a una cuenta de INEGI
  (**Settings → General → Transfer ownership**) o agregar a su responsable como administrador;
  volver a desplegar la app desde esa cuenta y actualizar los secretos si cambia el correo.

## Correr todo a mano (sin GitHub)

```bash
python -m pip install -r requirements.txt
python robot.py                     # hace lo mismo que la ejecución diaria
python robot.py --periodo 2026_T3   # forzar un trimestre
python calendario.py                # ver las próximas publicaciones
python -m streamlit run app.py      # dashboard local
```
