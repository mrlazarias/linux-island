# linux-island

Uma *dynamic island* para o Linux que fica no centro do painel, no lugar do relógio. Ela mostra **hora, data, clima e o que está tocando no Spotify**. Ao passar o mouse, ela se expande com a previsão dos próximos dias e os controles de mídia.

![Ilha compacta no painel](docs/compact.png)

![Ilha expandida](docs/expanded.png)

Feita para o **COSMIC** (Pop!_OS 24.04), mas deve funcionar em qualquer compositor Wayland com suporte a `wlr-layer-shell` (Hyprland, Sway, river, niri, KDE Plasma…).

## Recursos

- **Relógio e data** em português, em 24h.
- **Clima atual**: temperatura, condição, máxima, mínima e sensação térmica, via [Open-Meteo](https://open-meteo.com/), sem chave de API.
- **Previsão de 5 dias** com a chance de chuva.
- **Spotify** via MPRIS/D-Bus:
  - capa, título, artista e uma barra de progresso clicável e arrastável;
  - botões de anterior, play/pause e próxima;
  - o equalizador e a barra de progresso usam a cor predominante da capa;
  - a ilha abre sozinha por alguns segundos quando a faixa muda.
- **Animações**: a pílula muda de tamanho e de arredondamento ao expandir, e a capa e o equalizador deslizam pra dentro quando a música começa.
- **Leve**: Python + GTK3, sem polling de metadados. O Spotify avisa por D-Bus quando algo muda.

### Interação

| Ação | Resultado |
|---|---|
| Passar o mouse | expande |
| Clique esquerdo numa área livre | abre ou fecha |
| Clique do meio | play / pause |
| Clique direito | traz a janela do Spotify para frente |
| Clicar ou arrastar na barra | pula para o ponto da música |

## Instalação

Dependências (Ubuntu, Pop!_OS, Debian):

```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-gtklayershell-0.1
```

Depois:

```bash
git clone https://github.com/mrlazarias/linux-island.git
cd linux-island
./run.sh
```

<details>
<summary>Sem sudo? Use o gtk-layer-shell localmente</summary>

O `run.sh` usa automaticamente uma cópia do gtk-layer-shell em `vendor/`, se ela existir:

```bash
mkdir -p vendor/debs && cd vendor/debs
apt-get download gir1.2-gtklayershell-0.1 libgtk-layer-shell0
for f in *.deb; do dpkg-deb -x "$f" ../root; done
```

</details>

### Opções

```bash
./run.sh --city "Belo Horizonte"   # cidade do clima (padrão: detecta pelo IP)
./run.sh --margin 2                # distância do topo da tela, em px
```

### Substituir o relógio do COSMIC

A ilha fica por cima do painel. Para tirar o relógio original de baixo dela, remova o applet de hora do centro do painel. Isso pode ser feito nas configurações de applets do painel ou direto no arquivo:

```bash
P=~/.config/cosmic/com.system76.CosmicPanel.Panel/v1
cp $P/plugins_center $P/plugins_center.backup   # para voltar depois
printf 'Some([])' > $P/plugins_center
```

### Iniciar com a sessão

```bash
cat > ~/.config/autostart/linux-island.desktop <<EOF
[Desktop Entry]
Type=Application
Name=linux-island
Exec=$PWD/run.sh
NoDisplay=true
EOF
```

## Como funciona

| Arquivo | Papel |
|---|---|
| `island.py` | janela layer-shell (camada overlay, ancorada no topo), hover, cliques, animações de tamanho |
| `views.py` | conteúdo dos modos compacto e expandido |
| `widgets.py` | capa arredondada, equalizador e barra de progresso desenhados com cairo |
| `spotify.py` | cliente MPRIS (`org.mpris.MediaPlayer2.spotify`), posição interpolada e download da capa |
| `weather.py` | localização (cidade via geocoding do Open-Meteo ou IP via ipwho.is) e previsão |
| `style.css` | aparência |

Algumas particularidades descobertas no caminho:

- **Posição da música:** o Spotify não emite mudanças da propriedade `Position`. A posição é interpolada localmente e ressincronizada a cada ~3 s e no sinal `Seeked`.
- **Tamanho da janela:** janelas GTK3 não encolhem sozinhas. Durante as animações, a janela acompanha o tamanho do conteúdo a cada frame.
- **Hover:** no Wayland o GTK3 gera eventos `enter`/`leave` "fantasmas" ao cruzar as sub-janelas internas. Por isso o hover consulta onde o ponteiro realmente está.
- **Localização:** o GeoClue não responde sem um agente, como no COSMIC. Por isso a cidade vem do IP, ou de `--city`.

Para depurar, rode com `ISLAND_DEBUG=1 ./run.sh` e acompanhe os eventos no terminal.

## Privacidade

- Para descobrir a cidade, o seu IP é enviado ao [ipwho.is](https://ipwho.is/), a não ser que você use `--city`. O resultado fica em cache por 6 horas em `~/.cache/linux-island/`.
- As coordenadas são enviadas ao [Open-Meteo](https://open-meteo.com/) para buscar a previsão.
- As capas são baixadas do CDN do Spotify e guardadas em `~/.cache/linux-island/art/`.

## Roadmap

- [ ] Outros players MPRIS (Firefox, VLC, mpv…)
- [ ] Notificações na ilha
- [ ] Volume pela rolagem do mouse
- [ ] Idioma e formato de hora configuráveis
- [ ] Calendário no modo expandido

## Licença

[MIT](LICENSE)
