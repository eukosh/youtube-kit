#!/bin/bash
# Re-records the README demos with VHS (brew install vhs; font: brew install --cask font-jetbrains-mono)
# and rebuilds agent.gif, commands.gif and login.gif here, plus out/demo.mp4: all three in one captioned video.
#   ./record.sh          everything
#   ./record.sh agent    only the agent clip (it asks Claude a real question about your default channel)
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p out
(cd "$(git rev-parse --show-toplevel)" && uv sync --quiet)

BG=1e1e2e
W=1280
H=1110

seconds() { ffprobe -v error -show_entries format=duration -of csv=p=0 "$1"; }

# Terminal footage has flat colors: one palette and no dithering keep text sharp.
gif() {
  ffmpeg -v error -y -i "$1" -vf "fps=15,palettegen=max_colors=128" out/palette.png
  ffmpeg -v error -y -i "$1" -i out/palette.png -lavfi "fps=15[x];[x][1:v]paletteuse=dither=none:diff_mode=rectangle" "$2"
}

# The prompt at real speed, the agent's work at 3x, then 5s on the answer (the last big scene change).
edit_agent() {
  local raw=out/agent_raw.mp4 sent answer
  sent=$(ffmpeg -v info -i $raw -vf "select='gt(scene,0.004)',showinfo" -f null - 2>&1 | grep -oE 'pts_time:[0-9.]+' | head -1 | cut -d: -f2)
  answer=$(ffmpeg -v info -i $raw -vf "select='gt(scene,0.02)',showinfo" -f null - 2>&1 | grep -oE 'pts_time:[0-9.]+' | tail -1 | cut -d: -f2)
  ffmpeg -v error -y -i $raw -filter_complex "
    [0:v]trim=0:$sent,setpts=PTS-STARTPTS[a];
    [0:v]trim=$sent:$answer,setpts=(PTS-STARTPTS)/3[b];
    [0:v]trim=$answer:$(echo "$answer + 5" | bc),setpts=PTS-STARTPTS[c];
    [a][b][c]concat=n=3:v=1:a=0,fps=30,format=yuv420p[v]" -map "[v]" -c:v libx264 -crf 18 out/agent.mp4
}

svg() { # name height body
  printf '<svg xmlns="http://www.w3.org/2000/svg" width="%s" height="%s"><style>text{font-family:"JetBrains Mono"}</style>%s</svg>' \
    $W "$2" "$3" >"out/$1.svg"
  rsvg-convert "out/$1.svg" -o "out/$1.png"
}

# A clip under its caption, centered, sped up by $3, with $4 seconds cut from its closing hold.
scene() {
  local end
  end=$(echo "$(seconds "$1") - $4" | bc)
  svg "$2" 90 "<text x=\"50%\" y=\"60\" text-anchor=\"middle\" font-size=\"34\" font-weight=\"700\" fill=\"#cdd6f4\">$5</text>"
  ffmpeg -v error -y -i "$1" -i "out/$2.png" -filter_complex "
    [0:v]trim=0:$end,setpts=(PTS-STARTPTS)/$3,fps=30,pad=$W:$H:(ow-iw)/2:90+(oh-90-ih)/2:color=0x$BG[p];
    [p][1:v]overlay=0:0,format=yuv420p" -an -c:v libx264 -crf 18 "out/$2.mp4"
}

combine() {
  svg title $H "<rect width=\"100%\" height=\"100%\" fill=\"#$BG\"/>
    <g transform=\"translate(395,402)\"><rect width=\"180\" height=\"126\" rx=\"34\" fill=\"#ff0000\"/><path d=\"M72 36 L72 90 L120 63 Z\" fill=\"#fff\"/></g>
    <text x=\"605\" y=\"510\" font-size=\"150\" font-weight=\"800\" fill=\"#ff0000\">ytk</text>
    <text x=\"50%\" y=\"640\" text-anchor=\"middle\" font-size=\"42\" fill=\"#cdd6f4\">YouTube CLI and MCP server</text>
    <text x=\"50%\" y=\"705\" text-anchor=\"middle\" font-size=\"32\" fill=\"#9399b2\">built for agents and humans</text>"
  ffmpeg -v error -y -loop 1 -t 2.5 -r 30 -i out/title.png -vf format=yuv420p -c:v libx264 -crf 18 out/title.mp4
  scene out/agent.mp4 c1 1 2.5 'Ask your agent about your channel'
  scene out/commands.mp4 c2 1 1.8 'Or script it yourself: JSON out'
  scene out/login.mp4 c3 1.15 0 'One guided setup, then any of your channels'
  local fade=0.4 o1 o2 o3
  o1=$(echo "$(seconds out/title.mp4) - $fade" | bc)
  o2=$(echo "$o1 + $(seconds out/c1.mp4) - $fade" | bc)
  o3=$(echo "$o2 + $(seconds out/c2.mp4) - $fade" | bc)
  ffmpeg -v error -y -i out/title.mp4 -i out/c1.mp4 -i out/c2.mp4 -i out/c3.mp4 -filter_complex "
    [0][1]xfade=transition=fade:duration=$fade:offset=$o1[a];
    [a][2]xfade=transition=fade:duration=$fade:offset=$o2[b];
    [b][3]xfade=transition=fade:duration=$fade:offset=$o3,format=yuv420p[v]" \
    -map "[v]" -c:v libx264 -crf 18 -movflags +faststart out/demo.mp4
}

if [ "${1:-}" != agent ]; then
  vhs login.tape
  vhs commands.tape
fi
vhs agent.tape
edit_agent
gif out/agent.mp4 agent.gif
gif out/commands.mp4 commands.gif
gif out/login.mp4 login.gif
combine
ls -la ./*.gif out/demo.mp4
