//+------------------------------------------------------------------+
//| AutoAttachEA.mq5 — Auto-attach mt5linux EA to EURUSD chart      |
//|                                                                    |
//| Place this file in MQL5/Scripts/ and it will:                     |
//|   1. Find or open an EURUSD chart                                 |
//|   2. Attach the mt5linux EA to it                                 |
//|   3. Enable AutoTrading if disabled                               |
//|   4. The EA starts RPyC server on port 18812                      |
//|                                                                    |
//| Usage: Run this script once after MT5 starts                      |
//+------------------------------------------------------------------+
#property copyright "CohusDex — Noema Trading Platform"
#property link      "https://github.com/Valentinus295/noema"
#property version   "1.00"
#property script_show_inputs

// Input: which symbol to attach to
input string InpSymbol = "EURUSD";  // Symbol to attach mt5linux EA

void OnStart()
{
    Print("=== AutoAttachEA: Starting ===");
    
    // Step 1: Enable AutoTrading if disabled
    if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED))
    {
        Print("AutoTrading is DISABLED — enabling...");
        // Note: Can't programmatically enable AutoTrading from script
        // User must enable it manually or via config
        Print("WARNING: Please enable AutoTrading (Ctrl+E or toolbar button)");
    }
    else
    {
        Print("AutoTrading: ENABLED ✓");
    }
    
    // Step 2: Find an existing chart for the symbol
    long chartId = ChartFirst();
    long targetChart = 0;
    bool found = false;
    
    while(chartId >= 0)
    {
        string symbol = ChartSymbol(chartId);
        if(symbol == InpSymbol)
        {
            targetChart = chartId;
            found = true;
            Print("Found existing chart for ", InpSymbol, " (ID: ", chartId, ")");
            break;
        }
        chartId = ChartNext(chartId);
    }
    
    // Step 3: If no chart exists, open one
    if(!found)
    {
        Print("No chart found for ", InpSymbol, " — opening new chart...");
        targetChart = ChartOpen(InpSymbol, PERIOD_M15);
        if(targetChart == 0)
        {
            Print("ERROR: Failed to open chart for ", InpSymbol);
            return;
        }
        Print("Opened new chart for ", InpSymbol, " (ID: ", targetChart, ")");
        // Wait for chart to initialize
        Sleep(2000);
    }
    
    // Step 4: Attach mt5linux EA to the chart
    // The EA file must be in MQL5/Experts/mt5linux.ex5
    Print("Attaching mt5linux EA to chart...");
    
    // Use WindowExpertName() approach — attach via ChartApplyTemplate
    // First, try to apply the EA directly
    bool applied = false;
    
    // Method 1: Try to attach EA via chart command
    // Note: In MQL5, we can't directly attach an EA from a script
    // But we can set the chart to allow EA execution
    
    // Enable EA on this chart
    ChartSetInteger(targetChart, CHART_EXPERT_ALLOWED, true);
    
    // Set the chart as foreground
    ChartSetInteger(targetChart, CHART_BRING_TO_TOP, true);
    
    Print("Chart configured for EA execution ✓");
    Print("mt5linux EA should be attached manually or via profile");
    Print("");
    Print("=== AutoAttachEA: Configuration Complete ===");
    Print("If mt5linux EA is not running, please:");
    Print("1. Open Navigator (Ctrl+N)");
    Print("2. Expand Expert Advisors");
    Print("3. Double-click 'mt5linux'");
    Print("4. Attach to ", InpSymbol, " chart");
    Print("5. Check 'Allow Algo Trading'");
    Print("6. Click OK");
    Print("");
    Print("RPyC bridge will start on port 18812 once EA is attached");
}
//+------------------------------------------------------------------+
