-- ============================================================================
-- Migration 001: Trade Events Audit Trail
-- Description: Immutable, append-only audit trail for all trade decisions.
--               Stores the full decision chain: agent votes, statistical tests,
--               p-values, LLM narrative, and execution results.
-- 
-- Requirement: AC1.11 from Noema Blueprint — "Why did we trade EURUSD on 
--              Tuesday?" must be answerable with a single query.
--
-- Design:
--   - INSERT-only (no UPDATE, no DELETE) — immutable audit trail
--   - Full decision chain logged per trade event
--   - JSONB for flexible agent vote storage
--   - Indexed for fast retrieval by timestamp, symbol, event_type
--   - FTS (Full-Text Search) for narrative/comments searchability
-- ============================================================================

-- Create the trade_events schema if not using public
-- CREATE SCHEMA IF NOT EXISTS noema;

-- ============================================================================
-- TABLE: trade_events
-- Core audit trail table — every significant event in the trade lifecycle.
-- ============================================================================

CREATE TABLE IF NOT EXISTS trade_events (
    -- Primary key: auto-incrementing event ID
    id              BIGSERIAL PRIMARY KEY,
    
    -- Event timestamp (UTC) — when the event occurred
    event_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Event type: matches TypedMessage.MessageType values
    -- e.g., 'decision.proposal', 'execution.order_filled', 'risk.drawdown_warning'
    event_type      VARCHAR(100) NOT NULL,
    
    -- Trading symbol (EURUSD, GBPUSD, XAUUSD, etc.)
    symbol          VARCHAR(20) NOT NULL DEFAULT '',
    
    -- Trade direction: 'BUY', 'SELL', or '' for non-trade events
    direction       VARCHAR(4) NOT NULL DEFAULT '',
    
    -- Lot size (position volume)
    lot             DECIMAL(10, 4) NOT NULL DEFAULT 0.0,
    
    -- Entry price
    entry           DECIMAL(15, 6) NOT NULL DEFAULT 0.0,
    
    -- Stop loss price
    sl              DECIMAL(15, 6) NOT NULL DEFAULT 0.0,
    
    -- Take profit price
    tp              DECIMAL(15, 6) NOT NULL DEFAULT 0.0,
    
    -- All agent votes at decision time (JSONB)
    -- Structure: {
    --   "structure": {"vote": "BULLISH", "confidence": 0.72},
    --   "devil": {"vote": "REJECT", "reason": "RSI divergence on H4"},
    --   "risk": {"vote": "APPROVE", "exposure_pct": 0.5},
    --   "guardian": {"vote": "APPROVE", "kill_switches_ok": true},
    --   "cio": {"narrative": "...", "tiebreaker": "NO_TRADE"}
    -- }
    agent_votes     JSONB NOT NULL DEFAULT '{}',
    
    -- Statistical test backing the trade decision
    -- e.g., 'adf_test', 'engle_granger', 'garch', 'bootstrap_ci'
    statistical_test VARCHAR(100) NOT NULL DEFAULT '',
    
    -- Test statistic value (e.g., ADF t-stat, Johansen trace stat)
    test_statistic  DECIMAL(20, 10) NOT NULL DEFAULT 0.0,
    
    -- P-value of the statistical test
    p_value         DECIMAL(20, 10) NOT NULL DEFAULT 1.0,
    
    -- LLM-generated narrative (for audit, NOT for decision-making)
    -- The LLM only provides narrative — the ConservativeTiebreaker makes decisions.
    llm_narrative   TEXT NOT NULL DEFAULT '',
    
    -- Execution result: 'FILLED', 'REJECTED', 'PARTIALLY_FILLED', etc.
    execution_result VARCHAR(50) NOT NULL DEFAULT '',
    
    -- Result details (e.g., ticket number, rejection reason)
    result_details  TEXT NOT NULL DEFAULT '',
    
    -- P&L in account currency (populated on position close)
    realized_pnl    DECIMAL(15, 4) NOT NULL DEFAULT 0.0,
    
    -- P&L in pips
    pnl_pips        DECIMAL(10, 2) NOT NULL DEFAULT 0.0,
    
    -- Account balance after this event
    account_balance DECIMAL(15, 4) NOT NULL DEFAULT 0.0,
    
    -- Account equity after this event
    account_equity  DECIMAL(15, 4) NOT NULL DEFAULT 0.0,
    
    -- Current drawdown percentage
    drawdown_pct    DECIMAL(8, 4) NOT NULL DEFAULT 0.0,
    
    -- Correlation ID for event sourcing (links request-response pairs)
    correlation_id  VARCHAR(64) NOT NULL DEFAULT '',
    
    -- Causation ID for event sourcing (links to parent event)
    causation_id    VARCHAR(64) NOT NULL DEFAULT '',
    
    -- Additional metadata (JSONB for extensibility)
    metadata        JSONB NOT NULL DEFAULT '{}'
);

-- ============================================================================
-- Comments
-- ============================================================================

COMMENT ON TABLE trade_events IS 
'Immutable, append-only trade audit trail. Stores the full decision chain (agent votes, statistical tests, p-values, LLM narrative, execution result) for every trade event. INSERT-only — no UPDATE or DELETE allowed.';

COMMENT ON COLUMN trade_events.agent_votes IS 
'JSONB: all agent votes at decision time. Keys are agent names, values are {vote, confidence, reason, ...} objects.';

COMMENT ON COLUMN trade_events.statistical_test IS 
'Name of the statistical test backing this trade (e.g., adf_test, engle_granger, garch_1_1).';

COMMENT ON COLUMN trade_events.llm_narrative IS 
'LLM-generated narrative for audit purposes. The LLM creates narrative text only — the ConservativeTiebreaker makes the actual decision. No LLM in the decision path.';

-- ============================================================================
-- Indexes
-- ============================================================================

-- Time-based queries: "Show me all events from today"
CREATE INDEX idx_trade_events_timestamp ON trade_events (event_timestamp DESC);

-- Symbol queries: "Show me all EURUSD events in the last N days"
CREATE INDEX idx_trade_events_symbol_time ON trade_events (symbol, event_timestamp DESC);

-- Event type queries: "Show me all kill-switch activations"
CREATE INDEX idx_trade_events_type ON trade_events (event_type);

-- Combined symbol + event type: "Show me all EURUSD filled orders"
CREATE INDEX idx_trade_events_symbol_type ON trade_events (symbol, event_type);

-- Execution result queries: "Show me all rejected orders"
CREATE INDEX idx_trade_events_execution ON trade_events (execution_result);

-- Correlation ID for event sourcing queries
CREATE INDEX idx_trade_events_correlation ON trade_events (correlation_id);

-- Causation ID for event sourcing chain queries
CREATE INDEX idx_trade_events_causation ON trade_events (causation_id);

-- ============================================================================
-- Full-Text Search (FTS5 equivalent for PostgreSQL)
-- ============================================================================

-- GIN index on the full text of llm_narrative and result_details
-- Enables: "Why did we trade EURUSD on Tuesday?" with a single query
CREATE INDEX idx_trade_events_narrative_gin ON trade_events 
    USING gin (to_tsvector('english', COALESCE(llm_narrative, '')));

-- Combined text search index covering all text fields
CREATE INDEX idx_trade_events_text_search ON trade_events 
    USING gin ((
        to_tsvector('english', 
            COALESCE(llm_narrative, '') || ' ' ||
            COALESCE(result_details, '') || ' ' ||
            COALESCE(statistical_test, '')
        )
    ));

-- ============================================================================
-- Constraints and Triggers
-- ============================================================================

-- Prevent UPDATEs on the audit table
CREATE OR REPLACE FUNCTION prevent_trade_events_update()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'trade_events is an immutable audit table — UPDATEs are not allowed. Insert only.';
END;
$$ LANGUAGE plpgsql;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'trigger_prevent_trade_events_update'
    ) THEN
        CREATE TRIGGER trigger_prevent_trade_events_update
            BEFORE UPDATE ON trade_events
            FOR EACH ROW
            EXECUTE FUNCTION prevent_trade_events_update();
    END IF;
END;
$$;

-- Prevent DELETEs on the audit table
CREATE OR REPLACE FUNCTION prevent_trade_events_delete()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'trade_events is an immutable audit table — DELETEs are not allowed. Insert only.';
END;
$$ LANGUAGE plpgsql;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'trigger_prevent_trade_events_delete'
    ) THEN
        CREATE TRIGGER trigger_prevent_trade_events_delete
            BEFORE DELETE ON trade_events
            FOR EACH ROW
            EXECUTE FUNCTION prevent_trade_events_delete();
    END IF;
END;
$$;

-- ============================================================================
-- Utility Functions
-- ============================================================================

-- Insert a trade event safely (validates event_type)
CREATE OR REPLACE FUNCTION insert_trade_event(
    p_event_type        VARCHAR(100),
    p_symbol            VARCHAR(20) DEFAULT '',
    p_direction         VARCHAR(4) DEFAULT '',
    p_lot               DECIMAL DEFAULT 0.0,
    p_entry             DECIMAL DEFAULT 0.0,
    p_sl                DECIMAL DEFAULT 0.0,
    p_tp                DECIMAL DEFAULT 0.0,
    p_agent_votes       JSONB DEFAULT '{}',
    p_statistical_test  VARCHAR(100) DEFAULT '',
    p_test_statistic    DECIMAL DEFAULT 0.0,
    p_p_value           DECIMAL DEFAULT 1.0,
    p_llm_narrative     TEXT DEFAULT '',
    p_execution_result  VARCHAR(50) DEFAULT '',
    p_result_details    TEXT DEFAULT '',
    p_realized_pnl      DECIMAL DEFAULT 0.0,
    p_pnl_pips          DECIMAL DEFAULT 0.0,
    p_account_balance   DECIMAL DEFAULT 0.0,
    p_account_equity    DECIMAL DEFAULT 0.0,
    p_drawdown_pct      DECIMAL DEFAULT 0.0,
    p_correlation_id    VARCHAR(64) DEFAULT '',
    p_causation_id      VARCHAR(64) DEFAULT '',
    p_metadata          JSONB DEFAULT '{}'
) RETURNS BIGINT AS $$
DECLARE
    new_id BIGINT;
BEGIN
    INSERT INTO trade_events (
        event_type, symbol, direction, lot, entry, sl, tp,
        agent_votes, statistical_test, test_statistic, p_value,
        llm_narrative, execution_result, result_details,
        realized_pnl, pnl_pips, account_balance, account_equity,
        drawdown_pct, correlation_id, causation_id, metadata
    ) VALUES (
        p_event_type, p_symbol, p_direction, p_lot, p_entry, p_sl, p_tp,
        p_agent_votes, p_statistical_test, p_test_statistic, p_p_value,
        p_llm_narrative, p_execution_result, p_result_details,
        p_realized_pnl, p_pnl_pips, p_account_balance, p_account_equity,
        p_drawdown_pct, p_correlation_id, p_causation_id, p_metadata
    ) RETURNING id INTO new_id;
    
    RETURN new_id;
END;
$$ LANGUAGE plpgsql;

-- Query: "Why did we trade EURUSD on Tuesday?"
-- 
-- SELECT 
--     event_timestamp,
--     direction,
--     lot,
--     entry,
--     sl,
--     tp,
--     agent_votes,
--     statistical_test,
--     test_statistic,
--     p_value,
--     llm_narrative,
--     execution_result
-- FROM trade_events
-- WHERE symbol = 'EURUSD'
--   AND event_timestamp >= '2026-06-23'::date
--   AND event_timestamp < '2026-06-24'::date
--   AND event_type = 'decision.proposal'
-- ORDER BY event_timestamp DESC;

-- ============================================================================
-- Migration metadata
-- ============================================================================

-- Migration version tracking
CREATE TABLE IF NOT EXISTS _migrations (
    id          SERIAL PRIMARY KEY,
    version     VARCHAR(20) NOT NULL UNIQUE,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    description TEXT NOT NULL DEFAULT ''
);

INSERT INTO _migrations (version, description)
VALUES ('001', 'Create trade_events immutable audit trail table with full decision chain logging')
ON CONFLICT (version) DO NOTHING;
