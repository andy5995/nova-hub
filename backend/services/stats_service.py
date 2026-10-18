# backend/services/stats_service.py

from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from backend.core.clock import utcnow
from backend.core.config import get_config
from backend.models.database import Client, League, LeagueMembership, Packet, ProcessingRun, SequenceAlert


class StatsService:
    """Service for computing statistics.

    Given a Scope (backend/core/scope.py), the dashboard figures count only
    what that user may see; without one, everything.
    """

    def __init__(self, db: Session, scope=None):
        self.db = db
        self.scope = scope

    def _packets(self, query):
        clause = self.scope.packet_clause() if self.scope else None
        return query if clause is None else query.filter(clause)

    def get_dashboard_stats(self) -> Dict:
        """Get stats for dashboard"""
        now = datetime.now()
        day_ago = now - timedelta(days=1)

        clients = self.db.query(func.count(Client.id))
        leagues = self.db.query(func.count(League.id))
        alerts = self.db.query(func.count(SequenceAlert.id))
        if self.scope and not self.scope.is_admin:
            clients = clients.filter(Client.id.in_(self.scope.client_ids))
            leagues = leagues.filter(self.scope.league_clause(League.id))
            alerts = alerts.filter(self.scope.alert_clause())

        total_packets = self._packets(self.db.query(func.count(Packet.id))).scalar()
        total_clients = clients.scalar()
        active_clients = clients.filter(Client.is_active == True).scalar()
        active_leagues = leagues.filter(League.is_active == True).scalar()
        pending_alerts = alerts.filter(SequenceAlert.resolved_at == None).scalar()
        # The dashboard has always had cards for these; nothing filled them in.
        day_ago = utcnow() - timedelta(days=1)
        packets_24h = self._packets(
            self.db.query(func.count(Packet.id)).filter(Packet.uploaded_at >= day_ago)).scalar()
        runs = self.db.query(func.count(ProcessingRun.id)).filter(ProcessingRun.started_at >= day_ago)
        run_clause = self.scope.run_clause() if self.scope else None
        if run_clause is not None:
            runs = runs.filter(run_clause)
        processing_runs_24h = runs.scalar()

        return {
            "total_packets": total_packets or 0,
            "packets_24h": packets_24h or 0,
            "processing_runs_24h": processing_runs_24h or 0,
            "total_clients": total_clients or 0,
            "active_clients": active_clients or 0,
            "active_leagues": active_leagues or 0,
            "pending_alerts": pending_alerts or 0,
        }

    def get_recent_activity(self, limit: int = 20) -> List[Dict]:
        """Get recent packet activity"""
        packets = (
            self._packets(self.db.query(Packet))
            .order_by(Packet.uploaded_at.desc()).limit(limit).all()
        )

        # Who each packet was from or for, in three queries for the lot rather
        # than up to four a packet.
        client_ids = {c for p in packets for c in (p.source_client_id, p.dest_client_id) if c}
        league_ids = {p.league_id for p in packets}
        members = (self.db.query(LeagueMembership)
                   .filter(LeagueMembership.league_id.in_(league_ids)).all()) if league_ids else []
        client_ids |= {m.client_id for m in members}
        clients = ({c.id: c for c in self.db.query(Client).filter(Client.id.in_(client_ids))}
                   if client_ids else {})
        by_station = {}
        for m in sorted(members, key=lambda m: m.id, reverse=True):
            by_station[(m.league_id, m.bbs_index)] = m.client_id    # the oldest row wins
        hub = get_config().hub.bbs_index.upper()

        activity = []
        for packet in packets:
            # Determine if this is an upload or download
            # Upload: packet from remote BBS to hub
            # Download: packet from hub to remote BBS

            # Try to get client from packet's foreign keys first
            client = clients.get(packet.source_client_id or packet.dest_client_id)

            # If no client found via foreign keys, try looking up via LeagueMembership
            if not client:
                for index in (packet.source_bbs_index, packet.dest_bbs_index):
                    cid = by_station.get((packet.league_id, int(index, 16)))
                    if cid is not None:
                        client = clients.get(cid)
                        break

            activity_type = "upload" if packet.source_bbs_index.upper() != hub else "download"
            client_name = client.bbs_name if client else f"BBS {packet.source_bbs_index}"
            league_name = f"{packet.league.game_type} League {packet.league.league_id}"
            route = f"{packet.source_bbs_index} → {packet.dest_bbs_index}"

            # Build a description for the activity
            action_word = "uploaded" if activity_type == "upload" else "downloaded"
            description = f"{client_name} {action_word} {packet.filename} ({league_name}, {route})"

            activity.append(
                {
                    "id": packet.id,
                    "type": activity_type,
                    "description": description,
                    "client_name": client_name,
                    "filename": packet.filename,
                    "league_name": league_name,
                    "route": route,
                    "timestamp": self.format_timestamp(packet.uploaded_at),
                }
            )

        return activity

    def get_activity_chart_data(self, hours: int = 24) -> tuple:
        """Get packet activity for chart"""
        now = datetime.now()
        start = now - timedelta(hours=hours)

        # One query for the window, bucketed here: it was one query an hour.
        times = self._packets(
            self.db.query(Packet.uploaded_at)
            .filter(and_(Packet.uploaded_at >= start, Packet.uploaded_at < now))
        ).all()
        data = [0] * hours
        for (at,) in times:
            data[min(int((at - start).total_seconds() // 3600), hours - 1)] += 1
        labels = [(start + timedelta(hours=i)).strftime("%H:%M") for i in range(hours)]

        return labels, data

    def get_league_distribution(self) -> tuple:
        """Get packet distribution by league"""
        results = (
            self._packets(
                self.db.query(
                    League.game_type,
                    League.league_id,
                    func.count(Packet.id).label("count"),
                )
                .join(Packet)
            )
            .group_by(League.id)
            .all()
        )

        labels = [f"{r.game_type} {r.league_id}" for r in results]
        data = [r.count for r in results]

        return labels, data

    def get_client_stats(self, client_id: int, days: int = 1) -> Dict:
        """Get stats for a specific client"""
        client = self.db.query(Client).filter(Client.id == client_id).first()
        if not client:
            return None

        # Get client memberships to determine BBS indexes per league
        memberships = self.db.query(LeagueMembership).filter(
            LeagueMembership.client_id == client_id,
            LeagueMembership.is_active == True
        ).all()

        # Build list of (league_id, bbs_hex) tuples
        league_bbs_map = [(m.league_id, format(m.bbs_index, "02X")) for m in memberships]

        if not league_bbs_map:
            return {
                "total_sent": 0,
                "sent_24h": 0,
                "total_received": 0,
                "received_24h": 0,
                "last_seen": "Never",
            }

        cutoff = datetime.now() - timedelta(days=days)

        # Build filters for each league membership
        sent_filters = [
            and_(
                Packet.league_id == league_id,
                Packet.source_bbs_index == bbs_hex
            )
            for league_id, bbs_hex in league_bbs_map
        ]

        received_filters = [
            and_(
                Packet.league_id == league_id,
                Packet.dest_bbs_index == bbs_hex
            )
            for league_id, bbs_hex in league_bbs_map
        ]

        total_sent = (
            self.db.query(func.count(Packet.id))
            .filter(or_(*sent_filters))
            .scalar()
        )

        sent_recent = (
            self.db.query(func.count(Packet.id))
            .filter(
                and_(
                    or_(*sent_filters),
                    Packet.uploaded_at >= cutoff,
                )
            )
            .scalar()
        )

        total_received = (
            self.db.query(func.count(Packet.id))
            .filter(or_(*received_filters))
            .scalar()
        )

        received_recent = (
            self.db.query(func.count(Packet.id))
            .filter(
                and_(
                    or_(*received_filters),
                    Packet.uploaded_at >= cutoff,
                )
            )
            .scalar()
        )

        # Last seen - any packet where this client was source or dest in any league
        all_filters = sent_filters + received_filters
        last_packet = (
            self.db.query(Packet)
            .filter(or_(*all_filters))
            .order_by(Packet.uploaded_at.desc())
            .first()
        )

        last_seen = last_packet.uploaded_at if last_packet else None

        return {
            "total_sent": total_sent or 0,
            "sent_24h": sent_recent or 0,
            "total_received": total_received or 0,
            "received_24h": received_recent or 0,
            "last_seen": self.format_timestamp(last_seen) if last_seen else "Never",
        }

    def format_timestamp(self, dt: datetime) -> str:
        """Format timestamp as relative time"""
        if not dt:
            return "Never"

        now = datetime.now()
        diff = now - dt

        if diff.days > 0:
            return f"{diff.days} day{'s' if diff.days > 1 else ''} ago"
        elif diff.seconds >= 3600:
            hours = diff.seconds // 3600
            return f"{hours} hour{'s' if hours > 1 else ''} ago"
        elif diff.seconds >= 60:
            minutes = diff.seconds // 60
            return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
        else:
            return "Just now"
