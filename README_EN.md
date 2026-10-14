
[![GitHub License](https://img.shields.io/github/license/269289854/talebook-miku?style=flat-square)](LICENSE)
[![GitHub commit activity](https://img.shields.io/github/commit-activity/w/269289854/talebook-miku?logo=github&amp;style=flat-square&amp;label=commits)](https://github.com/269289854/talebook-miku/commits/main)
[![Tests](https://github.com/269289854/talebook-miku/actions/workflows/ci.yml/badge.svg)](https://github.com/269289854/talebook-miku/actions/workflows/ci.yml)
[![Docker Build](https://github.com/269289854/talebook-miku/actions/workflows/build.yml/badge.svg)](https://github.com/269289854/talebook-miku/actions/workflows/build.yml)


# Tale Book: My Calibre WebServer

[中文](README.md) | English

A better online books library management website built on Calibre + Vue

## A Simple and User-Friendly Personal Book Management System

This is a simple personal book management system based on Calibre, supporting **online reading**. Main features:
* Beautiful interface: A modern interface rebuilt with Nuxt 4 + Vue 3 + Vuetify, supporting both PC and mobile browsing, with multi-language (Chinese/English) support and light/dark theme switching;
* Multi-user support: Multi-user functionality with login via social platforms like ~~Douban~~ (deprecated), QQ, Weibo, Github, etc.; full user management and guest permission control, bcrypt password storage, image captcha and GeeTest verification;
* Online reading support: Built-in [candle-reader](https://github.com/talebook/candle-reader) for reading e-books in the browser, with automatic conversion for non-EPUB formats;
* Online library with book sources: Import [Legado](https://github.com/gedoor/legado)-style book sources to search and read web novels online, and save them to the library as txt/epub with one click; book source management UI with batch import, enable/disable and validity checks;
* Batch scan and import of books, with automatic metadata filling, recycle bin and batch deletion;
* Email push support: Manage multiple Kindle and other receiving devices, one-click push with automatic batch format conversion;
* OPDS support: Use apps like [KyBooks](http://kybook-reader.com/) for convenient reading; also browse and import books from other OPDS libraries;
* One-click installation, web-based initial configuration, easy website setup, with online update checking;
* Optimized file storage path for large libraries, can be categorized by alphabet or keep Chinese filenames;
* Quick update of book information: Search and import metadata in parallel from multiple sources (Douban, Baidu Encyclopedia, Xinhua Bookstore, Tomato Novel), with optional AI-powered book information recognition;
* Private mode support: Requires access code to enter the website, convenient for small group sharing; individual books can also be marked as private, visible only to yourself;

This project is a modified version of [talebook/talebook](https://github.com/talebook/talebook) (formerly calibre-webserver) and is now maintained independently in this repository; images, dependencies and update checks no longer rely on upstream.

## Highlights of the Past Year

* **Online library & book sources**: New Legado-style book source parsing engine — search and read web novels online and save them to the library as txt/epub; book source management UI (batch enable/disable/delete, validity checks, paginated search).
* **Frontend rewrite**: Upgraded from Nuxt 2 to Nuxt 4 + Vue 3 + Vuetify 3, full i18n (Chinese/English), light/dark theme switching, redesigned login/signup and book editing pages.
* **AI & multi-source metadata**: New AI-powered book information API; metadata sources extended to Douban, Baidu Encyclopedia, Xinhua Bookstore, Tomato Novel and Calibre, queried in parallel.
* **Online reading**: Default EPUB reader switched to [candle-reader](https://github.com/talebook/candle-reader); non-EPUB books are converted automatically before online reading.
* **Push & conversion**: New user device management with multi-device push; background batch conversion of Kindle-proprietary formats to EPUB.
* **OPDS import**: Add external OPDS sources, browse and batch import books, with failure retry and progress tracking.
* **Security hardening**: Automatic password migration from SHA256 to bcrypt; image captcha and GeeTest verification for login/signup/password reset; multiple security fixes (ReDoS, code injection, etc.).
* **Admin enhancements**: User management UI, guest upload permission control, recycle bin, batch book deletion, update checking, and a user feedback entry.
* **Infrastructure**: Upgraded to Tornado 6.5, switched to uv for Python dependency management, added database migration tooling; Docker base image consolidated into `talebook/talebook-base` for faster builds.


## Docker

Docker is the recommended deployment method. Images are published to [GitHub Container Registry](https://github.com/269289854/talebook-miku/pkgs/container/talebook-miku); pull them as `ghcr.io/269289854/talebook-miku`.

It is recommended to use `docker-compose`, download the configuration file [docker-compose.yml](docker-compose.yml) from the repository, and then execute the command to start.
If you want to modify the mounted directories or ports, please modify the docker-compose.yml file.

By default, the Compose file keeps Talebook settings, the user database, and the library together in `data/` next to `docker-compose.yml`. Rebuilding or replacing the container does not remove those files. Back up this directory regularly, and do not keep long-lived data under `/tmp`, which the host may clean. To use another location, set an absolute path in a colocated `.env` file:

```dotenv
TALEBOOK_DATA_DIR=/path/to/talebook-data
```

If an existing deployment still uses `/tmp/demo`, back it up before updating the Compose file and set `TALEBOOK_DATA_DIR=/tmp/demo` to keep mounting the existing data. Alternatively, migrate it while the container is stopped. Do not complete setup again without first mounting the original data.

```
wget https://raw.githubusercontent.com/269289854/talebook-miku/main/docker-compose.yml
docker-compose -f docker-compose.yml  up -d
```


If using native docker, then execute the command:

`docker run -d --name talebook -p &lt;local-port&gt;:80 -v &lt;local-data-directory&gt;:/data ghcr.io/269289854/talebook-miku`


For example

`mkdir -p "$PWD/data" && docker run -d --name talebook -p 8080:80 -v "$PWD/data:/data" ghcr.io/269289854/talebook-miku`



## FAQ

For frequently asked questions, please refer to the [User Guide](document/README.en_US.md). If you can't solve it, please submit an [issue](https://github.com/269289854/talebook-miku/issues).

For manual installation, please refer to the [Developer Guide](document/Development.en_US.md)

**Disclaimer! This project does not maintain any public book library sites. Sites like joyeuse, wenyuange, etc. are built by users. Please do not consult me about related issues, I can't help!**


## Contributors
[![](https://contrib.rocks/image?repo=269289854/talebook-miku)](https://github.com/269289854/talebook-miku/graphs/contributors)


## Demo



Project demo screenshot below:
![](document/screenshot.png)
