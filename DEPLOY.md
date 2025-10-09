# DEPLOY

## Servidor (Droplet) – 104.248.134.44 (porta 2202)

Pré-requisitos: Ubuntu, `ffmpeg`, `python3`, `pip`, `systemd`.

### 1) Copiar ficheiros (rsync)

```
# Ajuste o utilizador (p.ex., root) e o caminho local do projeto:
export DROPLET_USER=root
export DROPLET_IP=104.248.134.44
export DROPLET_PORT=2202
export SRC=.
export DEST=/root/bwb-stream2yt

rsync -avz --delete -e "ssh -p $DROPLET_PORT"   --exclude '*.env' --exclude 'token.json' --exclude 'client_secret.json'   "$SRC/secondary-droplet/" "$DROPLET_USER@$DROPLET_IP:$DEST/secondary-droplet/"
rsync -avz --delete -e "ssh -p $DROPLET_PORT" "$SRC/scripts/" "$DROPLET_USER@$DROPLET_IP:$DEST/scripts/"
```

### 2) Instalar dependências e serviços

No droplet:

```
apt-get update
apt-get install -y ffmpeg python3-pip fonts-dejavu-core
pip3 install -r /root/bwb-stream2yt/secondary-droplet/requirements.txt

# serviços
install -m 755 -o root -g root /root/bwb-stream2yt/secondary-droplet/bin/youtube_fallback.sh /usr/local/bin/youtube_fallback.sh
install -m 644 -o root -g root /root/bwb-stream2yt/secondary-droplet/systemd/youtube-fallback.service /etc/systemd/system/youtube-fallback.service
install -m 755 -o root -g root /root/bwb-stream2yt/secondary-droplet/bin/ensure_broadcast.py /usr/local/bin/ensure_broadcast.py
install -m 644 -o root -g root /root/bwb-stream2yt/secondary-droplet/systemd/ensure-broadcast.service /etc/systemd/system/ensure-broadcast.service
install -m 644 -o root -g root /root/bwb-stream2yt/secondary-droplet/systemd/ensure-broadcast.timer /etc/systemd/system/ensure-broadcast.timer

systemctl daemon-reload
systemctl enable --now youtube-fallback.service
systemctl enable --now ensure-broadcast.timer
```

### 3) Segredos no droplet (fora do git)

```
# YT_KEY (backup)
# post_deploy.sh irá regenerar o ficheiro preservando a chave e restaurando os defaults comentados.
printf 'YT_KEY="SUA_CHAVE_AQUI"\n' > /etc/youtube-fallback.env
chown root:root /etc/youtube-fallback.env
chmod 644 /etc/youtube-fallback.env
systemctl restart youtube-fallback

# OAuth token para YouTube Data API
# (gerar localmente e copiar) => /root/token.json  (chmod 600)
```

### 4) Decider (opcional se usar)

```
# colocar token.json e client_secret.json em /root/
# editar yt_decider_daemon.py se necessário e criar unit service própria
```

### 5) Atualizações posteriores

Use `scripts/deploy_to_droplet.sh` para sincronizar ficheiros e, em seguida, conecte via SSH (`ssh -p $DROPLET_PORT $DROPLET_USER@$DROPLET_IP`) para executar `bash /root/bwb-stream2yt/scripts/post_deploy.sh` manualmente.
