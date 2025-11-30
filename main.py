
# main_final2.py - Versão completa com melhorias visuais (Tema C), remoção de mediador por Dono/01/02,
# /fila2 com valores pré-definidos (inclui 0.50) e embeds redesenhadas.
# Atenção: este arquivo é pronto para uso — adicione seu TOKEN em bot.run(...) no final.
# Requisitos: nextcord, qrcode, Python 3.10+

import nextcord
from nextcord import Interaction, SlashOption
from nextcord.ext import commands
from nextcord.ui import View, Select
import qrcode
import io
import asyncio
import json
from typing import Dict, Set, Tuple, List, Optional
from datetime import datetime

# =====================================================================
# CONFIG
# =====================================================================
intents = nextcord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# =====================================================================
# THEME C - Estética "C"
# =====================================================================
# Paleta C: azul-escuro / ciano / roxo suave
COR_C_PRINCIPAL = color=nextcord.Color.from_rgb(69, 23, 118)  # #451776
COR_C_ACCENT = color=nextcord.Color.from_rgb(69, 23, 118)  # #451776
COR_C_SECOND = color=nextcord.Color.from_rgb(69, 23, 118)  # #451776

THUMBNAIL_URL = "https://imgur.com/a/oqMWnGW"           
SEPARATOR = "━━━━━━━━━━━━━━━━━━━━"

# =====================================================================
# PERSISTÊNCIA (pix + stats)
# =====================================================================
PIX_STORE_FILE = "pix_store.json"
STATS_FILE = "player_stats.json"

def load_pix_store() -> Dict[int, str]:
    try:
        with open(PIX_STORE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return {int(k): v for k, v in data.items()}
    except Exception:
        return {}

def save_pix_store(store: Dict[int, str]):
    with open(PIX_STORE_FILE, "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in store.items()}, f, ensure_ascii=False, indent=2)

def load_stats() -> Dict[int, Dict[str, int]]:
    try:
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return {int(k): v for k, v in data.items()}
    except Exception:
        return {}

def save_stats(stats: Dict[int, Dict[str, int]]):
    try:
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in stats.items()}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

pix_mediadores: Dict[int, str] = load_pix_store()
player_stats: Dict[int, Dict[str, int]] = load_stats()

# =====================================================================
# ESTADOS EM MEMÓRIA
# =====================================================================
fila_de_mediadores: List[int] = []
mediator_load: Dict[int, int] = {}        # {mediator_id: active_matches}
channel_mediator_map: Dict[int, int] = {} # {channel_id: mediator_id}
fila_para_mediador: Dict[str, int] = {}

jogadores_em_partida: Set[int] = set()
usuario_filas: Dict[int, Set[str]] = {}

mensagem_fila_mediador: Optional[nextcord.Message] = None
mensagem_fila_1v1: Optional[nextcord.Message] = None

removal_tasks: Dict[Tuple[str, int], asyncio.Task] = {}

# =====================================================================
# UTILIDADES
# =====================================================================
def gerar_qr_code(chave_pix: str, valor: float) -> io.BytesIO:
    dados_qr = f"PIX_KEY:{chave_pix}\\nVALOR:{valor:.2f}"
    qr = qrcode.make(dados_qr)
    img_io = io.BytesIO()
    qr.save(img_io, "PNG")
    img_io.seek(0)
    return img_io

def selecionar_mediador_por_load() -> Optional[int]:
    if not fila_de_mediadores:
        return None
    for m in fila_de_mediadores:
        mediator_load.setdefault(m, 0)
    return min(fila_de_mediadores, key=lambda mid: mediator_load.get(mid, 0))

def limitar_filas(user_id: int) -> bool:
    return len(usuario_filas.get(user_id, set())) < 2

def marcar_usuario_em_fila(user_id: int, fila_id: str):
    usuario_filas.setdefault(user_id, set()).add(fila_id)

async def remover_usuario_de_fila(fila_id: str, user_id: int):
    key = (fila_id, user_id)
    task = removal_tasks.pop(key, None)
    if task:
        try:
            task.cancel()
        except Exception:
            pass
    s = usuario_filas.get(user_id)
    if s and fila_id in s:
        s.remove(fila_id)
        if not s:
            usuario_filas.pop(user_id, None)

async def retirar_usuario_de_todas_filas(user: nextcord.Member):
    filas = list(usuario_filas.get(user.id, set()))
    for fid in filas:
        await remover_usuario_de_fila(fid, user.id)

async def agendar_remocao_por_timeout(fila_id: str, user: nextcord.Member, delay: int = 180):
    async def _wait_and_remove():
        try:
            await asyncio.sleep(delay)
            if fila_id in usuario_filas.get(user.id, set()) and user.id not in jogadores_em_partida:
                try:
                    await user.send(f"⏳ Você foi removido da fila `{fila_id}` por inatividade (3 minutos).")
                except Exception:
                    pass
                await remover_usuario_de_fila(fila_id, user.id)
        except asyncio.CancelledError:
            return
    task = asyncio.create_task(_wait_and_remove())
    removal_tasks[(fila_id, user.id)] = task

def ensure_player_stats(user_id: int):
    if user_id not in player_stats:
        player_stats[user_id] = {"wins": 0, "losses": 0}

def registrar_vitoria(vencedor_id: int, perdedor_id: int):
    ensure_player_stats(vencedor_id)
    ensure_player_stats(perdedor_id)
    player_stats[vencedor_id]["wins"] += 1
    player_stats[perdedor_id]["losses"] += 1
    save_stats(player_stats)

# =====================================================================
# HELPERS VISUAIS (embeds estilo C)
# =====================================================================
def make_embed(title: str, description: str = "", color: nextcord.Color = COR_C_PRINCIPAL) -> nextcord.Embed:
    embed = nextcord.Embed(title=title, description=description, color=color, timestamp=datetime.utcnow())
    embed.set_thumbnail(url=THUMBNAIL_URL)
    embed.set_footer(text="Tema C • Sistema de Filas", icon_url=THUMBNAIL_URL)
    return embed

# =====================================================================
# VIEWS: Pós-partida e Confirmação (corrigido select handling)
# =====================================================================
class PosPartidaView(View):
    def __init__(self, jogadores: List[nextcord.Member], mediador_id: int):
        super().__init__(timeout=None)
        self.jogadores = jogadores
        self.mediador_id = mediador_id

        options = [
            nextcord.SelectOption(label=jogadores[0].display_name, value="1"),
            nextcord.SelectOption(label=jogadores[1].display_name, value="2"),
        ]
        sel = Select(placeholder="Selecione o vencedor", options=options)
        sel.callback = self.selecionar_vencedor
        self.add_item(sel)

    async def selecionar_vencedor(self, interaction: Interaction):
        if interaction.user.id != self.mediador_id:
            return await interaction.response.send_message("❌ Apenas o mediador pode definir o vencedor.", ephemeral=True)

        sel = None
        for child in self.children:
            if isinstance(child, Select):
                sel = child
                break

        if not sel or not getattr(sel, "values", None):
            return await interaction.response.send_message("Erro: seleção inválida.", ephemeral=True)

        choice = sel.values[0]
        vencedor = self.jogadores[0] if choice == "1" else self.jogadores[1]
        perdedor = self.jogadores[1] if choice == "1" else self.jogadores[0]

        registrar_vitoria(vencedor.id, perdedor.id)

        # decrementa load do mediador associado a este canal (se existir)
        try:
            chan_id = interaction.channel.id
            mid = channel_mediator_map.pop(chan_id, None)
            if mid and mid in mediator_load:
                mediator_load[mid] = max(0, mediator_load[mid] - 1)
        except Exception:
            pass

        # resposta elegante
        embed = make_embed("🏆 Vencedor definido", f"**{vencedor.display_name}** foi declarado vencedor.\n{SEPARATOR}\nParabéns!")
        embed.add_field(name="Mediador", value=f"<@{self.mediador_id}>", inline=True)
        embed.add_field(name="Partida", value=f"{self.jogadores[0].display_name} vs {self.jogadores[1].display_name}", inline=True)
        await interaction.response.send_message(embed=embed)

        ensure_player_stats(vencedor.id)
        w = player_stats[vencedor.id]["wins"]
        l = player_stats[vencedor.id]["losses"]
        total = w + l
        wr = (w / total * 100) if total > 0 else 0.0

        stats_embed = make_embed(f"📊 Estatísticas — {vencedor.display_name}", color=COR_C_SECOND)
        stats_embed.add_field(name="🏆 Vitórias", value=str(w), inline=True)
        stats_embed.add_field(name="❌ Derrotas", value=str(l), inline=True)
        stats_embed.add_field(name="🔥 Winrate", value=f"{wr:.2f}%", inline=True)
        await interaction.channel.send(embed=stats_embed)

        for j in self.jogadores:
            jogadores_em_partida.discard(j.id)

        # apagar canal em background rapidamente (tenta)
        try:
            await asyncio.sleep(5)
            await interaction.channel.delete()
        except Exception:
            pass

    @nextcord.ui.button(label="Encerrar partida", style=nextcord.ButtonStyle.danger)
    async def encerrar(self, button, interaction: Interaction):
        if interaction.user.id != self.mediador_id:
            return await interaction.response.send_message("❌ Apenas o mediador pode encerrar.", ephemeral=True)
        for p in self.jogadores:
            jogadores_em_partida.discard(p.id)
        try:
            cid = interaction.channel.id
            mid = channel_mediator_map.pop(cid, None)
            if mid in mediator_load:
                mediator_load[mid] = max(0, mediator_load[mid] - 1)
        except Exception:
            pass
        await interaction.response.send_message("🛑 Partida encerrada pelo mediador.", ephemeral=False)
        try:
            await interaction.channel.delete()
        except Exception:
            pass

class ConfirmarPartidaView(View):
    def __init__(self, jogadores: List[nextcord.Member], tipo_fila: str, valor: float, mediador_id: Optional[int]):
        super().__init__(timeout=None)
        self.jogadores = jogadores
        self.tipo_fila = tipo_fila
        self.valor = valor
        self.mediador_id = mediador_id
        self.confirmados: Set[int] = set()

    def is_jogador(self, user: nextcord.User) -> bool:
        return any(user.id == j.id for j in self.jogadores)

    async def atualizar_embed(self, mensagem: nextcord.Message):
        confirm_count = len(self.confirmados)
        nomes = ", ".join(j.display_name for j in self.jogadores)
        embed = make_embed("♜ Confirmação da Partida", color=COR_C_PRINCIPAL)
        embed.description = (f"{SEPARATOR}\n**{nomes}**\n\n**Confirmem que já combinaram gelo/armas e estão prontos.**\n\n✔ Confirmados: `{confirm_count}/{len(self.jogadores)}`\n{SEPARATOR}")
        try:
            await mensagem.edit(embed=embed, view=self)
        except Exception:
            pass

    @nextcord.ui.button(label="✔ Confirmar", style=nextcord.ButtonStyle.success)
    async def confirmar(self, button, interaction: Interaction):
        if not self.is_jogador(interaction.user):
            return await interaction.response.send_message("❌ Apenas os jogadores podem confirmar.", ephemeral=True)
        if interaction.user.id in self.confirmados:
            return await interaction.response.send_message("⚠ Você já confirmou.", ephemeral=True)
        self.confirmados.add(interaction.user.id)
        await interaction.response.send_message("✔ Confirmação registrada!", ephemeral=True)
        try:
            await self.atualizar_embed(interaction.message)
        except Exception:
            pass
        if len(self.confirmados) == len(self.jogadores):
            try:
                await interaction.message.delete()
            except Exception:
                pass
            await self.enviar_pix_e_pospartida(interaction.channel)

    @nextcord.ui.button(label="❌ Cancelar", style=nextcord.ButtonStyle.danger)
    async def cancelar(self, button, interaction: Interaction):
        if not self.is_jogador(interaction.user):
            return await interaction.response.send_message("❌ Apenas os jogadores podem cancelar.", ephemeral=True)
        canal = interaction.channel
        for j in self.jogadores:
            jogadores_em_partida.discard(j.id)
        await interaction.response.send_message("❌ A partida foi cancelada! Canal será apagado.", ephemeral=False)
        try:
            await canal.delete()
        except Exception:
            pass

    async def enviar_pix_e_pospartida(self, canal: nextcord.TextChannel):
        mediador_id = self.mediador_id
        chave = pix_mediadores.get(mediador_id) if mediador_id else None
        if not chave:
            await canal.send("❌ Nenhuma chave Pix registrada para esta fila. Avise o mediador.")
        else:
            valor_total = self.valor + 0.20
            qr = gerar_qr_code(chave, valor_total)
            embed = make_embed("💰 Pagamento - Pix", color=COR_C_PRINCIPAL)
            embed.add_field(name="Valor total", value=f"R$ {valor_total:.2f}", inline=True)
            embed.add_field(name="Chave Pix", value=f"`{chave}`", inline=True)
            embed.set_image(url="attachment://qr.png")
            await canal.send(embed=embed, file=nextcord.File(qr, "qr.png"))
            await canal.send("📌 Após o pagamento, aguardem o mediador confirmar para começar a partida.")

        view = PosPartidaView(self.jogadores, self.mediador_id if self.mediador_id else 0)
        embed_ctrl = make_embed("🎮 Controle da Partida", color=COR_C_SECOND)
        embed_ctrl.description = f"{SEPARATOR}\nApenas o mediador pode definir o vencedor entre os dois capitães ou encerrar o chat.\n{SEPARATOR}"
        await canal.send(embed=embed_ctrl, view=view)

# =====================================================================
# VIEWS: Filas (1v1, postar 1v1, times)
# =====================================================================
class Fila1View(View):
    def __init__(self, fila_id: str, valor: float):
        super().__init__(timeout=None)
        self.fila_id = fila_id
        self.valor = valor
        self.jogadores: List[Tuple[nextcord.Member, str]] = []

    def esta_na_fila(self, user_id: int) -> bool:
        return any(j.id == user_id for j, _ in self.jogadores)

    def pode_entrar(self, member: nextcord.Member) -> Tuple[bool, str]:
        if member.id in jogadores_em_partida:
            return False, "Você já está em uma partida ativa."
        if not limitar_filas(member.id):
            return False, "❌ Você já está em 2 filas. Saia de uma primeiro."
        if len(self.jogadores) >= 100:
            return False, "Fila cheia."
        return True, ""

    async def adicionar_jogador(self, member: nextcord.Member, modo: str, interaction: Interaction):
        ok, msg = self.pode_entrar(member)
        if not ok:
            return await interaction.response.send_message(msg, ephemeral=True)

        for idx, (j, m) in enumerate(self.jogadores):
            if j.id == member.id:
                if m == modo:
                    return await interaction.response.send_message("Você já está nesta fila neste modo.", ephemeral=True)
                else:
                    self.jogadores[idx] = (member, modo)
                    await interaction.response.send_message(f"🔁 Você mudou para o modo: {modo}", ephemeral=True)
                    await self.atualizar_embed(interaction)
                    par = self.encontrar_par_compatível()
                    if par:
                        (j1, modo1), (j2, modo2) = par
                        await self._criar_canal_privado(interaction, j1, modo1, j2, modo2)
                    return

        self.jogadores.append((member, modo))
        marcar_usuario_em_fila(member.id, self.fila_id)
        await agendar_remocao_por_timeout(self.fila_id, member, delay=180)
        await interaction.response.send_message(f"✅ Você entrou na fila 1v1 (modo: {modo})!", ephemeral=True)
        await self.atualizar_embed(interaction)

        par = self.encontrar_par_compatível()
        if par:
            (j1, modo1), (j2, modo2) = par
            await self._criar_canal_privado(interaction, j1, modo1, j2, modo2)

    def encontrar_par_compatível(self) -> Optional[Tuple[Tuple[nextcord.Member, str], Tuple[nextcord.Member, str]]]:
        modos_map: Dict[str, List[Tuple[nextcord.Member, str]]] = {}
        for jogador, modo in self.jogadores:
            modos_map.setdefault(modo, []).append((jogador, modo))
        for modo_check in ["Normal", "Gelo Infinito"]:
            if modo_check in modos_map and len(modos_map[modo_check]) >= 2:
                return modos_map[modo_check][0], modos_map[modo_check][1]
        return None

    @nextcord.ui.button(label="Entrar (Normal)", style=nextcord.ButtonStyle.success)
    async def entrar_normal(self, button, interaction: Interaction):
        await self.adicionar_jogador(interaction.user, "Normal", interaction)

    @nextcord.ui.button(label="Entrar (Gelo Infinito)", style=nextcord.ButtonStyle.primary)
    async def entrar_gelo(self, button, interaction: Interaction):
        await self.adicionar_jogador(interaction.user, "Gelo Infinito", interaction)

    @nextcord.ui.button(label="Sair", style=nextcord.ButtonStyle.danger)
    async def sair(self, button, interaction: Interaction):
        removed = None
        for item in list(self.jogadores):
            if item[0].id == interaction.user.id:
                removed = item
                break
        if removed:
            self.jogadores.remove(removed)
            await remover_usuario_de_fila(self.fila_id, interaction.user.id)
            await interaction.response.send_message("Você saiu da fila.", ephemeral=True)
            await self.atualizar_embed(interaction)
        else:
            await interaction.response.send_message("Você não está na fila.", ephemeral=True)

    async def atualizar_embed(self, interaction: Interaction):
        descricao = (f"{SEPARATOR}\n" +
                     ("\n".join([f"• **{m.display_name}** — `{modo}`" for m, modo in self.jogadores])
                      if self.jogadores else "Nenhum jogador entrou ainda.") +
                     f"\n{SEPARATOR}")
        embed = make_embed("♜ Fila 1v1 • Jogadores", descricao, color=COR_C_PRINCIPAL)
        embed.add_field(name="💰 Preço", value=f"R$ {self.valor:.2f} (+ R$ 0.20 taxa)", inline=False)
        embed.add_field(name="⚔ Modo", value="1v1", inline=True)
        embed.set_footer(text=f"Jogadores na fila: {len(self.jogadores)} • Tema C", icon_url=THUMBNAIL_URL)
        try:
            await interaction.message.edit(embed=embed, view=self)
        except Exception:
            pass

    async def _criar_canal_privado(self, interaction: Interaction, j1: nextcord.Member, modo1: str, j2: nextcord.Member, modo2: str):
        for m in [j1, j2]:
            jogadores_em_partida.add(m.id)
            key = (self.fila_id, m.id)
            task = removal_tasks.pop(key, None)
            if task:
                try:
                    task.cancel()
                except Exception:
                    pass

        self.jogadores = [(m, md) for (m, md) in self.jogadores if m.id not in (j1.id, j2.id)]
        await remover_usuario_de_fila(self.fila_id, j1.id)
        await remover_usuario_de_fila(self.fila_id, j2.id)
        await retirar_usuario_de_todas_filas(j1)
        await retirar_usuario_de_todas_filas(j2)

        mediador_id = selecionar_mediador_por_load()
        fila_para_mediador[self.fila_id] = mediador_id

        if mediador_id:
            mediator_load.setdefault(mediador_id, 0)
            mediator_load[mediador_id] += 1

        guild = interaction.guild
        overwrites = {guild.default_role: nextcord.PermissionOverwrite(read_messages=False)}
        overwrites[j1] = nextcord.PermissionOverwrite(read_messages=True)
        overwrites[j2] = nextcord.PermissionOverwrite(read_messages=True)
        if mediador_id:
            mediador_member = guild.get_member(mediador_id)
            if mediador_member:
                overwrites[mediador_member] = nextcord.PermissionOverwrite(read_messages=True)

        canal_name = f"partida-{j1.name}-vs-{j2.name}"
        canal = await guild.create_text_channel(canal_name, overwrites=overwrites)

        try:
            channel_mediator_map[canal.id] = mediador_id
        except Exception:
            pass

        modo_text = f"\n• {j1.display_name}: {modo1}\n• {j2.display_name}: {modo2}"
        embed = make_embed("⚔ Confirmação da Partida", color=COR_C_PRINCIPAL)
        embed.description = f"{SEPARATOR}\n{j1.mention} e {j2.mention}\n\n**Confirmem que já combinaram gelo/armas e estão prontos.**{modo_text}\n{SEPARATOR}"
        view = ConfirmarPartidaView([j1, j2], self.fila_id, self.valor, mediador_id)
        await canal.send(embed=embed, view=view)
        try:
            await self.atualizar_embed(interaction)
        except Exception:
            pass

class Fila1PostView(View):
    def __init__(self, fila_id: str, valor: float):
        super().__init__(timeout=None)
        self.fila_id = fila_id
        self.valor = valor
        self.jogadores: List[Tuple[nextcord.Member, str]] = []

    def esta_na_fila(self, user_id: int) -> bool:
        return any(j.id == user_id for j, _ in self.jogadores)

    def pode_entrar(self, member: nextcord.Member) -> Tuple[bool, str]:
        if member.id in jogadores_em_partida:
            return False, "Você já está em uma partida ativa."
        if self.esta_na_fila(member.id):
            return False, "Você já está nesta fila."
        if not limitar_filas(member.id):
            return False, "❌ Você já está em 2 filas. Saia de uma primeiro."
        if len(self.jogadores) >= 100:
            return False, "Fila cheia."
        return True, ""

    @nextcord.ui.button(label="Entrar", style=nextcord.ButtonStyle.success)
    async def entrar(self, button, interaction: Interaction):
        ok, msg = self.pode_entrar(interaction.user)
        if not ok:
            return await interaction.response.send_message(msg, ephemeral=True)
        self.jogadores.append((interaction.user, "Normal"))
        marcar_usuario_em_fila(interaction.user.id, self.fila_id)
        await agendar_remocao_por_timeout(self.fila_id, interaction.user, delay=180)
        await interaction.response.send_message("✅ Você entrou na fila 1v1!", ephemeral=True)
        await self.atualizar_embed(interaction)
        if len(self.jogadores) == 2:
            await self._criar_canal_privado(interaction)

    @nextcord.ui.button(label="Sair", style=nextcord.ButtonStyle.danger)
    async def sair(self, button, interaction: Interaction):
        found = None
        for item in list(self.jogadores):
            if item[0].id == interaction.user.id:
                found = item
                break
        if found:
            self.jogadores.remove(found)
            await remover_usuario_de_fila(self.fila_id, interaction.user.id)
            await interaction.response.send_message("Você saiu da fila.", ephemeral=True)
            await self.atualizar_embed(interaction)
        else:
            await interaction.response.send_message("Você não está na fila.", ephemeral=True)

    async def atualizar_embed(self, interaction: Interaction):
        descricao = (f"{SEPARATOR}\n" +
                     ("\n".join([f"• **{m.display_name}** — `{modo}`" for m, modo in self.jogadores])
                      if self.jogadores else "Nenhum jogador entrou ainda.") +
                     f"\n{SEPARATOR}")
        embed = make_embed("♜ Fila 1v1 • Painel", descricao, color=COR_C_PRINCIPAL)
        embed.add_field(name="💰 Preço", value=f"R$ {self.valor:.2f} (+ R$ 0.20)", inline=False)
        embed.set_footer(text=f"Entradas: {len(self.jogadores)} • Theme C", icon_url=THUMBNAIL_URL)
        try:
            await interaction.message.edit(embed=embed, view=self)
        except Exception:
            pass

    async def _criar_canal_privado(self, interaction: Interaction):
        (j1, modo1), (j2, modo2) = self.jogadores
        for m, _ in [(j1, modo1), (j2, modo2)]:
            jogadores_em_partida.add(m.id)
            key = (self.fila_id, m.id)
            t = removal_tasks.pop(key, None)
            if t:
                try:
                    t.cancel()
                except Exception:
                    pass
        await retirar_usuario_de_todas_filas(j1)
        await retirar_usuario_de_todas_filas(j2)

        mediador_id = selecionar_mediador_por_load()
        fila_para_mediador[self.fila_id] = mediador_id

        if mediador_id:
            mediator_load.setdefault(mediador_id, 0)
            mediator_load[mediador_id] += 1

        guild = interaction.guild
        overwrites = {guild.default_role: nextcord.PermissionOverwrite(read_messages=False)}
        overwrites[j1] = nextcord.PermissionOverwrite(read_messages=True)
        overwrites[j2] = nextcord.PermissionOverwrite(read_messages=True)
        if mediador_id:
            mm = guild.get_member(mediador_id)
            if mm:
                overwrites[mm] = nextcord.PermissionOverwrite(read_messages=True)

        canal_name = f"partida-{j1.name}-vs-{j2.name}"
        canal = await guild.create_text_channel(canal_name, overwrites=overwrites)

        try:
            channel_mediator_map[canal.id] = mediador_id
        except Exception:
            pass

        modo_text = f"\n• {j1.display_name}: {modo1}\n• {j2.display_name}: {modo2}"
        embed = make_embed("⚔ Confirmação da Partida", color=COR_C_PRINCIPAL)
        embed.description = f"{SEPARATOR}\n{j1.mention} e {j2.mention}\n\n**Confirmem que já combinaram gelo/armas e estão prontos.**{modo_text}\n{SEPARATOR}"
        view = ConfirmarPartidaView([j1, j2], self.fila_id, self.valor, mediador_id)
        await canal.send(embed=embed, view=view)
        self.jogadores = []

class FilaTimesView(View):
    def __init__(self, fila_id: str, valor: float, modo_label: int):
        super().__init__(timeout=None)
        self.fila_id = fila_id
        self.valor = valor
        self.modo_label = modo_label
        self.jogadores: List[Tuple[nextcord.Member, str]] = []

    def esta_na_fila(self, user_id: int) -> bool:
        return any(j.id == user_id for j, _ in self.jogadores)

    def pode_entrar(self, member: nextcord.Member) -> Tuple[bool, str]:
        if member.id in jogadores_em_partida:
            return False, "Você já está em uma partida ativa."
        if self.esta_na_fila(member.id):
            return False, "Você já está nesta fila."
        if not limitar_filas(member.id):
            return False, "❌ Você já está em 2 filas. Saia de uma primeiro."
        if len(self.jogadores) >= 2:
            return False, "Fila cheia."
        return True, ""

    @nextcord.ui.button(label="Entrar", style=nextcord.ButtonStyle.success)
    async def entrar(self, button, interaction: Interaction):
        ok, msg = self.pode_entrar(interaction.user)
        if not ok:
            return await interaction.response.send_message(msg, ephemeral=True)
        self.jogadores.append((interaction.user, "Normal"))
        marcar_usuario_em_fila(interaction.user.id, self.fila_id)
        await agendar_remocao_por_timeout(self.fila_id, interaction.user, delay=180)
        await interaction.response.send_message("✅ Você entrou na fila!", ephemeral=True)
        await self.atualizar_embed(interaction)
        if len(self.jogadores) == 2:
            await self._criar_canal_privado(interaction)

    @nextcord.ui.button(label="Sair", style=nextcord.ButtonStyle.danger)
    async def sair(self, button, interaction: Interaction):
        found = None
        for item in list(self.jogadores):
            if item[0].id == interaction.user.id:
                found = item
                break
        if found:
            self.jogadores.remove(found)
            await remover_usuario_de_fila(self.fila_id, interaction.user.id)
            await interaction.response.send_message("Você saiu da fila.", ephemeral=True)
            await self.atualizar_embed(interaction)
        else:
            await interaction.response.send_message("Você não está na fila.", ephemeral=True)

    async def atualizar_embed(self, interaction: Interaction):
        descricao = (f"{SEPARATOR}\n" +
                     ("\n".join([f"• **{m.display_name}**" for m, modo in self.jogadores])
                      if self.jogadores else "Nenhum jogador entrou ainda.") +
                     f"\n{SEPARATOR}")
        embed = make_embed(f"♜ Fila {self.modo_label}v{self.modo_label} • Captains", descricao, color=COR_C_PRINCIPAL)
        embed.add_field(name="💰 Preço", value=f"R$ {self.valor:.2f} (+ R$ 0.20)", inline=False)
        embed.add_field(name="⚔ Modo", value=f"{self.modo_label}v{self.modo_label}", inline=True)
        try:
            await interaction.message.edit(embed=embed, view=self)
        except Exception:
            pass

    async def _criar_canal_privado(self, interaction: Interaction):
        (j1, m1), (j2, m2) = self.jogadores
        for m, _ in [(j1, m1), (j2, m2)]:
            jogadores_em_partida.add(m.id)
            key = (self.fila_id, m.id)
            t = removal_tasks.pop(key, None)
            if t:
                try:
                    t.cancel()
                except Exception:
                    pass
        await retirar_usuario_de_todas_filas(j1)
        await retirar_usuario_de_todas_filas(j2)

        mediador_id = selecionar_mediador_por_load()
        fila_para_mediador[self.fila_id] = mediador_id

        if mediador_id:
            mediator_load.setdefault(mediador_id, 0)
            mediator_load[mediador_id] += 1

        guild = interaction.guild
        overwrites = {guild.default_role: nextcord.PermissionOverwrite(read_messages=False)}
        overwrites[j1] = nextcord.PermissionOverwrite(read_messages=True)
        overwrites[j2] = nextcord.PermissionOverwrite(read_messages=True)
        if mediador_id:
            mm = guild.get_member(mediador_id)
            if mm:
                overwrites[mm] = nextcord.PermissionOverwrite(read_messages=True)

        canal_name = f"partida-{j1.name}-vs-{j2.name}"
        canal = await guild.create_text_channel(canal_name, overwrites=overwrites)

        try:
            channel_mediator_map[canal.id] = mediador_id
        except Exception:
            pass

        modo_text = f"\n• {j1.display_name}: Normal\n• {j2.display_name}: Normal"
        embed = make_embed(f"⚔ Confirmação ({self.modo_label}v{self.modo_label})", color=COR_C_PRINCIPAL)
        embed.description = f"{SEPARATOR}\n{j1.mention} e {j2.mention}\n\n**Confirmem que estão prontos.**{modo_text}\n{SEPARATOR}"
        view = ConfirmarPartidaView([j1, j2], self.fila_id, self.valor, mediador_id)
        await canal.send(embed=embed, view=view)

        self.jogadores = []
        try:
            await self.atualizar_embed(interaction)
        except Exception:
            pass

# =====================================================================
# VIEW: Fila Mediador (embed fixa e atualizavel) + seletor/remoção (Dono/01/02)
# =====================================================================
def role_allowed_to_remove(member: nextcord.Member) -> bool:
    allowed_names = {"Dono", "01", "02"}
    return any(r.name in allowed_names for r in member.roles)

class RemoveMediatorSelect(Select):
    def __init__(self, options):
        super().__init__(placeholder="Escolha mediador para remover", min_values=1, max_values=1, options=options)

class FilaMediadorView(View):
    def __init__(self):
        super().__init__(timeout=None)
        # o select será atualizado na criação da view em atualizar_embed_fila_mediador

    @nextcord.ui.button(label="Entrar como Mediador", style=nextcord.ButtonStyle.success)
    async def entrar_mediador(self, button, interaction: Interaction):
        mediador_role = nextcord.utils.get(interaction.guild.roles, name="Mediador")
        if mediador_role not in interaction.user.roles:
            return await interaction.response.send_message("❌ Apenas membros com o cargo Mediador podem entrar.", ephemeral=True)
        if interaction.user.id not in pix_mediadores:
            return await interaction.response.send_message("❌ Cadastre sua chave Pix com /pix_registrar antes de entrar.", ephemeral=True)
        if interaction.user.id in fila_de_mediadores:
            return await interaction.response.send_message("⚠ Você já está na fila de mediadores.", ephemeral=True)
        fila_de_mediadores.append(interaction.user.id)
        mediator_load.setdefault(interaction.user.id, 0)
        await interaction.response.send_message("✅ Você entrou na fila de mediadores.", ephemeral=True)
        await atualizar_embed_fila_mediador(interaction.channel)

    @nextcord.ui.button(label="Sair da fila de mediadores", style=nextcord.ButtonStyle.danger)
    async def sair_mediador(self, button, interaction: Interaction):
        if interaction.user.id in fila_de_mediadores:
            fila_de_mediadores.remove(interaction.user.id)
            mediator_load.pop(interaction.user.id, None)
            await interaction.response.send_message("Você saiu da fila de mediadores.", ephemeral=True)
            await atualizar_embed_fila_mediador(interaction.channel)
        else:
            await interaction.response.send_message("Você não está na fila de mediadores.", ephemeral=True)

    # Este botão apenas remove o mediador selecionado no select acima (sem confirmação).
    @nextcord.ui.button(label="Remover mediador (Dono/01/02)", style=nextcord.ButtonStyle.secondary)
    async def remover_mediador_btn(self, button, interaction: Interaction):
        # verifica permissão
        if not role_allowed_to_remove(interaction.user):
            return await interaction.response.send_message("❌ Você não tem permissão para remover mediadores.", ephemeral=True)

        # procura select no view (deve ter sido criado por atualizar_embed_fila_mediador)
        sel = None
        for child in self.children:
            if isinstance(child, Select):
                sel = child
                break
        if not sel or not getattr(sel, "values", None):
            return await interaction.response.send_message("❌ Selecione o mediador a remover no menu antes.", ephemeral=True)

        try:
            value = sel.values[0]
            mid = int(value)
            if mid in fila_de_mediadores:
                fila_de_mediadores.remove(mid)
                mediator_load.pop(mid, None)
                await interaction.response.send_message(f"✅ Mediador <@{mid}> removido da fila.", ephemeral=True)
                await atualizar_embed_fila_mediador(interaction.channel)
            else:
                await interaction.response.send_message("⚠ Mediador não encontrado na fila.", ephemeral=True)
        except Exception:
            await interaction.response.send_message("Erro ao remover mediador.", ephemeral=True)

async def atualizar_embed_fila_mediador(channel: Optional[nextcord.TextChannel] = None):
    global mensagem_fila_mediador
    nomes = []
    options = []
    for uid in fila_de_mediadores:
        m = None
        for g in bot.guilds:
            m = g.get_member(uid)
            if m:
                break
        display = m.display_name if m else str(uid)
        nomes.append(display)
        options.append(nextcord.SelectOption(label=display, value=str(uid)))

    descricao = SEPARATOR + "\n" + ("\n".join([f"• **{n}**" for n in nomes]) if nomes else "Nenhum mediador na fila.") + "\n" + SEPARATOR
    embed = make_embed("♜ Fila de Mediadores", descricao, color=COR_C_PRINCIPAL)
    embed.add_field(name="Observação", value="Mediadores só podem entrar se tiverem Pix cadastrado (use /pix_registrar). Donos podem remover.", inline=False)
    view = FilaMediadorView()
    # adiciona select com as opções atuais (se houver)
    if options:
        sel = RemoveMediatorSelect(options)
        view.add_item(sel)
    try:
        if mensagem_fila_mediador:
            await mensagem_fila_mediador.edit(embed=embed, view=view)
            return
    except Exception:
        pass
    if channel:
        mensagem_fila_mediador = await channel.send(embed=embed, view=view)

# =====================================================================
# SLASH COMMANDS
# =====================================================================
@bot.slash_command(name="fila", description="Criar uma fila 1v1 (apenas Dono)")
async def cmd_fila(interaction: Interaction, valor: float = SlashOption(description="Valor da partida")):
    dono = nextcord.utils.get(interaction.guild.roles, name="Dono")
    if not dono or dono not in interaction.user.roles:
        return await interaction.response.send_message("❌ Apenas Donos podem criar filas.", ephemeral=True)
    fila_id = f"fila_{str(valor).replace('.', '_')}"
    view = Fila1View(fila_id, valor)
    descricao = f"{SEPARATOR}\n💰 **Preço:** `R$ {valor:.2f} + R$ 0.20 taxa`\nClique nos botões abaixo para entrar.\n{SEPARATOR}"
    embed = make_embed("♜ Fila 1v1 • Modo C", descricao, color=COR_C_PRINCIPAL)
    await interaction.response.send_message(embed=embed, view=view)

@bot.slash_command(name="postar_fila_1v1", description="(Dono) Posta/atualiza a embed fixa da fila 1v1 neste canal (Entrar/Sair)")
async def cmd_postar_fila_1v1(interaction: Interaction, valor: float = SlashOption(description="Valor da partida")):
    dono = nextcord.utils.get(interaction.guild.roles, name="Dono")
    if not dono or dono not in interaction.user.roles:
        return await interaction.response.send_message("❌ Apenas Donos podem postar a embed global.", ephemeral=True)
    global mensagem_fila_1v1
    fila_id = f"fila_{str(valor).replace('.', '_')}"
    view = Fila1PostView(fila_id, valor)
    embed = make_embed("♜ Fila 1v1 • Painel Oficial", color=COR_C_PRINCIPAL)
    embed.description = f"{SEPARATOR}\n💰 **Valor:** `R$ {valor:.2f} + R$ 0.20 taxa`\nUse os botões abaixo para entrar ou sair.\n{SEPARATOR}"
    if mensagem_fila_1v1:
        try:
            await mensagem_fila_1v1.edit(embed=embed, view=view)
            await interaction.response.send_message("Embed 1v1 atualizada.", ephemeral=True)
            return
        except Exception:
            mensagem_fila_1v1 = None
    msg = await interaction.channel.send(embed=embed, view=view)
    mensagem_fila_1v1 = msg
    await interaction.response.send_message("Embed 1v1 postada.", ephemeral=True)

# /fila2 com presets: o usuário escolhe 'modo' (2/3/4) e pode usar preset values via string choices
@bot.slash_command(name="fila2", description="Criar uma fila 2v2 | 3v3 | 4v4 (apenas Dono). Use valor ou preset.")
async def cmd_fila2(
    interaction: Interaction,
    modo: int = SlashOption(description="Escolha 2, 3 ou 4", choices={ "2":2, "3":3, "4":4 }),
    valor: float = SlashOption(description="Valor livre (opcional)", required=False, default=0.0),
    preset: str = SlashOption(description="Valores pré-definidos (opcional)", required=False, choices={"0.50":"0.5","2":"2","5":"5","10":"10","50":"50"})
):
    dono = nextcord.utils.get(interaction.guild.roles, name="Dono")
    if not dono or dono not in interaction.user.roles:
        return await interaction.response.send_message("❌ Apenas Donos podem criar filas.", ephemeral=True)

    # determina valor final: preset tem prioridade se fornecido
    final_valor = None
    if preset:
        try:
            final_valor = float(preset)
        except:
            final_valor = float(valor) if valor else 0.0
    else:
        final_valor = float(valor) if valor else 0.0

    fila_id = f"fila2_{modo}_{str(final_valor).replace('.', '_')}"
    view = FilaTimesView(fila_id, final_valor, modo)
    embed = make_embed(f"♜ Fila {modo}v{modo} • Painel", color=COR_C_PRINCIPAL)
    embed.description = f"{SEPARATOR}\n💰 **Preço:** `R$ {final_valor:.2f} + R$ 0.20 taxa`\nClique em Entrar para participar.\n{SEPARATOR}"
    await interaction.response.send_message(embed=embed, view=view)

@bot.slash_command(name="filas_mediador", description="Entrar/Ver fila de mediadores")
async def cmd_filas_mediador(interaction: Interaction):
    mediador_role = nextcord.utils.get(interaction.guild.roles, name="Mediador")
    if not mediador_role or mediador_role not in interaction.user.roles:
        return await interaction.response.send_message("❌ Você precisa ter o cargo Mediador.", ephemeral=True)
    if interaction.user.id not in pix_mediadores:
        return await interaction.response.send_message("❌ Cadastre sua chave Pix com /pix_registrar antes de entrar.", ephemeral=True)
    if interaction.user.id in fila_de_mediadores:
        return await interaction.response.send_message("⚠ Você já está na fila de mediadores.", ephemeral=True)
    fila_de_mediadores.append(interaction.user.id)
    mediator_load.setdefault(interaction.user.id, 0)
    await interaction.response.send_message(f"✅ Você entrou na fila de mediadores! Total: {len(fila_de_mediadores)}", ephemeral=True)
    await atualizar_embed_fila_mediador(interaction.channel)

@bot.slash_command(name="pix_registrar", description="Registrar sua chave Pix (somente mediadores)")
async def cmd_pix_registrar(interaction: Interaction, chave: str = SlashOption(description="Sua chave Pix")):
    mediador_role = nextcord.utils.get(interaction.guild.roles, name="Mediador")
    if not mediador_role or mediador_role not in interaction.user.roles:
        return await interaction.response.send_message("❌ Apenas mediadores podem registrar Pix.", ephemeral=True)
    pix_mediadores[interaction.user.id] = chave
    save_pix_store(pix_mediadores)
    await interaction.response.send_message(f"✅ Chave Pix registrada com sucesso!\nChave: `{chave}`", ephemeral=True)

@bot.slash_command(name="pix_remover", description="Remover sua chave Pix")
async def cmd_pix_remover(interaction: Interaction):
    if interaction.user.id in pix_mediadores:
        pix_mediadores.pop(interaction.user.id)
        save_pix_store(pix_mediadores)
        await interaction.response.send_message("✅ Sua chave Pix foi removida.", ephemeral=True)
    else:
        await interaction.response.send_message("⚠ Você não tem uma chave Pix registrada.", ephemeral=True)

@bot.slash_command(name="postar_fila_mediador", description="(Dono) Posta/atualiza a embed fixa da fila de mediadores neste canal")
async def cmd_postar_fila_mediador(interaction: Interaction):
    dono = nextcord.utils.get(interaction.guild.roles, name="Dono")
    if not dono or dono not in interaction.user.roles:
        return await interaction.response.send_message("❌ Apenas Donos podem postar a embed global.", ephemeral=True)
    await interaction.response.send_message("✅ Embed de fila de mediadores postada/atualizada.", ephemeral=True)
    await atualizar_embed_fila_mediador(interaction.channel)

# =====================================================================
# COMANDOS DE ESTATÍSTICAS (+p e !p)
# =====================================================================
@bot.command(name="p")
async def cmd_p(ctx, member: nextcord.Member = None):
    member = member or ctx.author
    ensure_player_stats(member.id)
    stats = player_stats.get(member.id, {"wins": 0, "losses": 0})
    wins = stats["wins"]
    losses = stats["losses"]
    total = wins + losses
    winrate = (wins / total * 100) if total > 0 else 0.0

    embed = make_embed(f"📊 Estatísticas de {member.display_name}", color=COR_C_SECOND)
    embed.add_field(name="🏆 Vitórias", value=str(wins), inline=True)
    embed.add_field(name="❌ Derrotas", value=str(losses), inline=True)
    embed.add_field(name="🔥 Winrate", value=f"{winrate:.2f}%", inline=True)
    await ctx.send(embed=embed)

@bot.event
async def on_message(message: nextcord.Message):
    if message.author.bot:
        return
    content = message.content.strip()
    if content.startswith("+p"):
        parts = content.split()
        member = None
        if len(parts) >= 2:
            if message.mentions:
                member = message.mentions[0]
            else:
                try:
                    mid = int(parts[1].strip("<@!>"))
                    member = message.guild.get_member(mid) if message.guild else None
                except Exception:
                    member = None
        member = member or message.author
        ensure_player_stats(member.id)
        stats = player_stats.get(member.id, {"wins": 0, "losses": 0})
        wins = stats["wins"]
        losses = stats["losses"]
        total = wins + losses
        winrate = (wins / total * 100) if total > 0 else 0.0
        embed = make_embed(f"📊 Estatísticas de {member.display_name}", color=COR_C_SECOND)
        embed.add_field(name="🏆 Vitórias", value=str(wins), inline=True)
        embed.add_field(name="❌ Derrotas", value=str(losses), inline=True)
        embed.add_field(name="🔥 Winrate", value=f"{winrate:.2f}%", inline=True)
        await message.channel.send(embed=embed)
        return
    await bot.process_commands(message)

# =====================================================================
# ON READY
# =====================================================================
@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user}")

# =====================================================================
# RUN
# =====================================================================
# RUN (adaptado para Koyeb: usa variável de ambiente DISCORD_TOKEN)
# =====================================================================
import os
import sys
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot")

if __name__ == "__main__":
    TOKEN = os.environ.get("DISCORD_TOKEN")
    if not TOKEN:
        logger.error("ERRO: variável de ambiente DISCORD_TOKEN não definida. Configure o token no Koyeb.")
        sys.exit(1)

    try:
        bot.run(TOKEN)
    except Exception as e:
        logger.exception("Erro ao iniciar o bot:")
        raise
