<div align="center">

# 📷 Fabula

A clean, lightweight, self-hosted photo gallery designed for tech-savvy photographers and photography enthusiasts, built with Flask.

![HTML5](https://img.shields.io/badge/html5-%23E34F26.svg?style=for-the-badge&logo=html5&logoColor=white) ![CSS3](https://img.shields.io/badge/css3-%231572B6.svg?style=for-the-badge&logo=css3&logoColor=white) ![JavaScript](https://img.shields.io/badge/javascript-%23323330.svg?style=for-the-badge&logo=javascript&logoColor=white) ![Flask](https://img.shields.io/badge/flask-%23000.svg?style=for-the-badge&logo=flask&logoColor=white)

</div>

<div align="center">
  <img src="/mockup.png?raw=true" alt="Mockup" width="700">
</div>

## Getting Started

### Installation

1. Clone the repo

```sh
 git clone https://github.com/S4kur4/fabula.git
```

2. Create username and password for managing photos

```sh
 /bin/bash account_init.sh
```
3. Modify `.env` to add your personal configuration

```
# (Optional) Google Analytics ID or Umami ID
GOOGLE_ANALYTICS_ID=
UMAMI_WEBSITE_ID=
```
```
# (Optional) Cloudflare Turnstile key to protect login form
TURNSTILE_SITE_KEY=
TURNSTILE_SECRET_KEY=
```
```
# Website title
TITTLE='Vivian Kent Photography'
```
```
# You can set the username and password directly here
# Note that the ADMIN_PASSWORD must be your password-hashed SHA256 value
ADMIN_USERNAME=admin
ADMIN_PASSWORD=
```
4.  Launch with `docker-compose`

```sh
docker-compose up -d
```

5. Use Nginx, Caddy and anyother popular web servers to point to `127.0.0.1:5001`

### Media and About Content Management

Click "Manage" or visit `/manage` to login and manage your photos and about content.

1. Go to `/manage`
2. Switch to the **Media** or **About** tab
3. Upload/remove photos or edit albums
3. Edit Heading / About Me / Signature / Gear / Contact
4. Click **Save About**

About content is stored in the SQLite database (`gallery.db`).

## Support Me on Ko-fi

I create this project because I'm passionate about photography. If you'd like to support my work and help me dedicate more time to it, please consider supporting on Ko-fi. Thank you for your generosity!

<a href='https://ko-fi.com/E1E416MCAU' target='_blank'><img height='36' style='border:0px;height:36px;' src='https://storage.ko-fi.com/cdn/kofi6.png?v=6' border='0' alt='Buy Me a Coffee at ko-fi.com' /></a>
