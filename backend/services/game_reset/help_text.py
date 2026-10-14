"""The games' own help for every reset setting, word for word.

Copied from the help files BRE and FE show in the reset editor (RESET.HLP),
with the colour codes and the decorated title line removed. The title is kept
separately: the driver checks it to know which field the editor opened. Two
lines the editor prints after a toggle ("This option has been toggled", "The
setting for this option has been switched") are dropped; they are not help.
Typos are the games', kept as they are.

Generated once from the .HLP files and committed; the games will not change.
"""

# field id -> (help title as the editor shows it, help text)
BRE = {
    'start_date': (
        'Start Date',
        'The Start Date Configuration allows you to reset the game earlier than\n'
        'actually starting.  This option is very useful for League Coordinators\n'
        'in Inter-BBS games to force all systems to start on the same date (using\n'
        'league-wide reset).  This option is also useful for Tournament games in\n'
        'which you want to allow players to sign up early.'
    ),
    'join_date': (
        'Join Date',
        'The Join Date option allows the sysop (or LC) to determine the last\n'
        'date a player can join the game.  This is useful for restricting access\n'
        'to latercomers in the game for tournaments, etc.'
    ),
    'turns_per_day': (
        'Turns Per Day',
        'The number of turns per day controls how quickly a game will progress.\n'
        'Normal games are generally around 8 turns per day, while quick games\n'
        'may go to 10-12.  The maximum amount, 20, will create a very quick\n'
        'paced game that will consume large amounts of player time and is\n'
        'recommended to only be used in rare instances.'
    ),
    'protection_turns': (
        'Turns Of Protection',
        'The number of turns of protection controls the number of turns for\n'
        'which a new empire is unable to attack, trade, and be attacked.  This\n'
        'is to allow small newcomers to join the game without immediately\n'
        'being destroyed.'
    ),
    'initial_land': (
        'Initial Market Land',
        'This option refers to the amount of land available to buy for a player\n'
        'at the beginning of the game.  Land is also created daily and a new\n'
        'player always has the option of buying up to 300 regions of land.  An\n'
        'initial value of 0 will give no advantage to the first few players,\n'
        'while a medium or high setting, depending on the number of turns per\n'
        'day, may be advantageous to the first players.'
    ),
    'land_per_day': (
        'Daily Land Creation',
        'This amount is the number of regions added to the market each day.  The\n'
        'regions are added as the day progresses.  The larger the value here, the\n'
        'faster growth each BBS in the game will have.  Smaller values will\n'
        'generally base strength more on attacks.'
    ),
    'interest_rate': (
        'Bank Interest Rate',
        'This is the amount of interest the bank will give in 10 days.  Interest\n'
        'is given to the player at the end of each turn.  In many InterBBS games,\n'
        'the interest rates and investments in the banks are exploited to an\n'
        'extent making the game investment-oriented; for these games, we highly\n'
        'recommend a low interest value (below 40%).  The maximum value, 200%, is\n'
        'equivalent to 20% interest per day in previous versions versions below\n'
        'v0.950.'
    ),
    'investment_rate': (
        'Basic Investment Interest Rate',
        'This is the amount of interest the bank will give in 10 days on investments\n'
        'at the beginning of the game.  Each day, if the Steady Investment Rate\n'
        'option is not enabled, the rate will change based on the amount of\n'
        'investing on the system, but will always be centered around this value. In\n'
        'many InterBBS games, the interest rates and investments in the banks are\n'
        'exploited to an extent making the game overflow; for these games, we highly\n'
        'recommend a low interest value (below 50%).  The maximum value, 100%, is\n'
        'equivalent to 10% interest per day.\n'
        'day.'
    ),
    'steady_investment': (
        'Steady Investment Interest Rate',
        'With this option disabled, investment interest rates will drop (possibly\n'
        'down to 1/2 the initial value) if there is too much investing going on.\n'
        'On the other end, with little investing going on, the rate can double the\n'
        'initial value.  If you do not wish have this rate changing, you can enable\n'
        'this option.'
    ),
    'tax_rate': (
        'Planetary Tax Rate',
        'The Tax rate can be used to control the growth of empires.  A high tax\n'
        'rate will generally equalise the size of baronies by "stealing from the\n'
        'rich and giving to the poor", while low tax rates allow large empires to\n'
        'grow much more easily.  Tax Refunds given daily are based on the total\n'
        'amount of income the BBS recieves in taxes.  Randomly throughout the\n'
        'game, the "BBS emperor" will raise or lower tax rates; therefore, the\n'
        'value set here is not binding, but provides an average, and initial,\n'
        'value for the game.'
    ),
    'max_region_purchase': (
        'Maximum Region Purchases',
        'This option limits the number of regions a player can buy in a single turn\n'
        'to prevent players with large amounts of cash from suddenly "jumping" in\n'
        'regions.  This value works in combination with the region pricing system,\n'
        'which can scale costs upward, except when a small\n'
        'empire receives large amounts of cash from an ally.'
    ),
    'max_players': (
        'Maximum Players',
        'This setting determines the maximum number of players on a system.  The\n'
        'normal maximum is 25, but smaller leagues may wish to lower the value\n'
        'to distribute players more evenly.  Leagues consisting primarily of local\n'
        "BBS's may wish to use this option to make game play more competitive by\n"
        'dividing the players up.'
    ),
    'buy_military': (
        'Buy Military',
        'This setting allows you to control military purchasing.  The "Yes" option\n'
        'creates a game in which military purchasing is unlimited, as in all versions\n'
        'before v0.960.  The "No" setting disables all military purchasing, forcing\n'
        'forcing players to produce using industrial regions.  The "Limited" option\n'
        'creates a limited amount of military in the market each day for purchasing.\n'
        'The "No" and "Limited" options force new strategies, reducing the usefulness\n'
        'of massive investing, while increasing the importance of owning regions.\n'
        'Additionally, overnight armies become almost impossible.'
    ),
    'maintenance_costs': (
        'GamePlay: Maintenance Costs',
        'The GamePlay options may be set to the following values: High, Medium\n'
        'Low, or None.  [H,M,L,N]  Some settings will not be allowed for certain\n'
        'options.  The Maintenance cost option sets the amount that must be paid to\n'
        'maintain military & regions in the pay-section of the game.  The higher\n'
        'setting will cause slower & more controlled growth rates, as well as smaller\n'
        'militaries.\n'
        'It may be set to either High, Medium, Low, or None - Default is Medium.'
    ),
    'trade_costs': (
        'GamePlay: Trade Costs',
        'The GamePlay options may be set to the following values: High, Medium\n'
        'Low, or None.  [H,M,L,N]  Some settings will not be allowed for certain\n'
        'options.  The Trade Cost option affects the amount of money charged when\n'
        'sending out trade deals.  A Low setting will encourage trading while a high\n'
        'setting limits trading to more important times.\n'
        'It may be set to either High, Medium, Low, or None - Default is Medium.'
    ),
    'region_costs': (
        'GamePlay: Region Costs',
        'The GamePlay options may be set to the following values: High, Medium\n'
        'Low, or None.  [H,M,L,N]  Some settings will not be allowed for certain\n'
        'options.  The Region Cost option affects the amount of money charged when\n'
        'purchasing new regions.  A Low setting will encourage purchases while a high\n'
        'setting makes war a more viable alternative.  The None setting will cause a\n'
        'minimal price increase in regions as purchased.\n'
        'It may be set to either High, Medium, Low, or None - Default is Medium.'
    ),
    'attack_damage': (
        'GamePlay: Attack Damage',
        'Some settings will not be allowed for certain\n'
        'options.  The Attack Damage option defines the amount of forces destroyed in\n'
        'combat.  A High setting will likely reduce combat & make strategy more\n'
        'important, while a low setting will make constant warfare with less strategy\n'
        'a more useful tactic.\n'
        'It may be set to either High, Medium, or Low - Default is Medium.'
    ),
    'attack_rewards': (
        'GamePlay: Attack Region Gains',
        'Some settings will not be allowed for certain\n'
        'options.  The Attack Region Gains option affects the number of regions won\n'
        'in all attacks. A High setting will make attacking more devastating while a\n'
        'low setting will make it more difficult to destroy smaller empires.\n'
        'It may be set to either High, Medium, or Low - Default is Medium.'
    ),
    'sabre': (
        'Sabre Handling',
        'The S3-Sabre is a variable-return missile.  Capable of a variety of\n'
        'special effects, this missile, when controlled, can be extremely\n'
        'devastating.\n'
        '\n'
        'Beginning with version 0.988 of BRE, the Sabre missle feature may be\n'
        'controlled via a configurable option as some players find the Sabre\n'
        'feature unfair due to the huge impact that it can have on game play.'
    ),
    'attack_costs': (
        'GamePlay: Attack Costs',
        'The GamePlay options may be set to the following values: High, Medium\n'
        'Low, or None.  [H,M,L,N]  Some settings will not be allowed for certain\n'
        'options.  The Attack Cost option affects the amount of money charged when\n'
        'sending InterBBS attacks. A High setting will make attacking more\n'
        'difficult for larger empires.\n'
        'It may be set to either High, Medium, Low, or None - Default is Medium.'
    ),
    'terrorist_costs': (
        'GamePlay: Terrorism Costs',
        'The GamePlay options may be set to the following values: High, Medium\n'
        'Low, or None.  [H,M,L,N]  Some settings will not be allowed for certain\n'
        'options.  The Terrorism Cost option affects the amount of money charged when\n'
        'sending InterBBS Terrorists. A High setting will make terrorism less\n'
        'popular.\n'
        'It may be set to either High, Medium, Low, or None - Default is Medium.'
    ),
    'indiv_attacks': (
        'InterBBS: Max Individual Attacks',
        'The number of individual Inter-BBS Attacks allowed per day should generally\n'
        'be kept low to prevent larger empires from destroying a smaller opponent\n'
        'in several strikes at once.  For some leagues, though, such as free-for-all\n'
        'leagues or whatever, you may wish to experiment with higher values. :)'
    ),
    'group_attacks': (
        'InterBBS: Max Group Attacks',
        'The number of group Inter-BBS Attacks allowed per day should generally\n'
        'be kept low to prevent larger empires from destroying a smaller opponent\n'
        'in several strikes at once.  For some leagues, though, such as free-for-all\n'
        'leagues or whatever, you may wish to experiment with higher values. :)'
    ),
    'terrorist_ops': (
        'InterBBS: Max Terrorist Operations',
        'The number of terrorist operations allowed per day can now be configured\n'
        "to fit your league's desire.  It is highly recommended to keep a fairly\n"
        'small value here, such as 10 or 15.'
    ),
    'bombings': (
        'InterBBS: Max Bombing Operations',
        'The number of bombings operations allowed per day can now be configured\n'
        "to fit your league's desire.  Originally, it was infinite, but often\n"
        'literally hundreds of bombing operations are sent and I thought I should\n'
        'offer some type of control for this.  We recommend a setting around\n'
        '5 or 10 ops a day.'
    ),
    'lost_attack_days': (
        'InterBBS: Lost Attack Prevention',
        'BRE supports logging of attacks and lost attack prevention.  If an attack\n'
        'has not returned after a certain number of days, the forces will be\n'
        'returned to the owner and the attack voided.  If the attack is to return\n'
        'in the future, it will not be processed, pretending that the assault was\n'
        'never made.  The number of days should be kept a little bit larger than\n'
        'the maximum turn around time for attacks from one BBS to another.  League\n'
        'Coordinators, please be sure to take into consideration the maximum time\n'
        'from any system in your league to any other, as the values you set will\n'
        'be used at all other systems in your league.'
    ),
    'gooie': (
        'InterBBS: Gooie Kablooies',
        'One of the special forms of attacks in BRE is to send a "Gooie Kablooie"\n'
        'to another BBS.  It is an expensive, but often powerful device.  In certain\n'
        'games, this feature may be harmful to gameplay.  If you are designing your\n'
        'setup to be primarily region-oriented (low interest rates, limited or no\n'
        'buying of military, etc), you may wish to consider disabling this feature\n'
        'so as to add more parity to the game.'
    ),
    'bombing_ops': (
        'InterBBS: Bombing Operations',
        'One of the special forms of attacks in BRE is to send bombs to destroy\n'
        'Food Markets, Investments, Trading Markets, etc. on another BBS.  Depending\n'
        'on your setup, you may wish to disable this feature.  We generally\n'
        'recommend leaving Bombing Operations enabled for most setups.'
    ),
    'missile_ops': (
        'InterBBS: Missile Operations',
        'One of the special forms of attacks in BRE is to send Nuclear, Chemical,\n'
        'and other special missiles to destroy enemy facilities.  Depending on your\n'
        'setup, you may wish to disable this feature (one example may be in heavily\n'
        'region-oriented games).  We generally recommend leaving Missile Operations\n'
        'enabled for most setups.'
    ),
    'local_attacks': (
        'InterBBS: Local Attacks',
        'This option enables or disables the ability to attack other local empires\n'
        'in Interplanetary games.  Leaving this option enabled,\n'
        "forces BBS's to use teamwork to remove troublemakers and allowing a\n"
        'method to destroy spies, etc.  Leaving it disabled limits the ability of moles\n'
        'to cause local damage during a campaign.'
    ),
    'local_scoring': (
        'InterBBS: Local Attack Scoring',
        'Enabling this option in an Interplanetary game will make BRE add score\n'
        'points to players who attack and defeat local opponents.  When disabled,\n'
        'score cannot be achieved through local fighting.  We recommend disabling\n'
        'this option, so that users cannot attack each other just to build up\n'
        'score.'
    ),
    'dupe_checking': (
        'InterBBS: Duplicate User Checking',
        'Enabling this feature will make BRE look for users on your system that may\n'
        'be playing on other BBSes and temporarily lock them out of the game (until\n'
        "they delete one of their players).  In general, long-distance games don't\n"
        'require this option as much as local games may.  Leaving this feature OFF\n'
        'will save some data transferring, but allows players to play on several\n'
        'systems more easily.'
    ),
    'league_wide': (
        'InterBBS: League-Wide Reset',
        'Selecting this will send reset information to all other systems in the\n'
        'league, automatically resetting their games without sysop intervention.\n'
        'This can be used if you wish to end league play and restart the game\n'
        'fresh or if problems have developed requiring a league-wide reset.'
    ),
}

FE = {
    'start_date': (
        'Start Date',
        'The Start Date Configuration allows you to reset the game earlier than\n'
        'actually starting.  This option is very useful for League Coordinators\n'
        'in Inter-BBS games to force all systems to start on the same date (using\n'
        'league-wide reset).  This option is also useful for Tournament games in\n'
        'which you want to allow players to sign up early.'
    ),
    'join_date': (
        'Join Date',
        'The Join Date option allows the sysop (or LC) to determine the last\n'
        'date a player can join the game.  This is useful for restricting access\n'
        'to latercomers in the game for tournaments, etc.'
    ),
    'turns_per_day': (
        'Turns Per Day',
        'The number of turns per day controls how quickly a game will progress.\n'
        'Normal games are generally around 6-8 turns per day, while quick games\n'
        'may go to 10 or 12.  The maximum amount will create a very quick paced game\n'
        'that will consume large amounts of player time and is recommended to\n'
        "only be used in rare instances.  Until you're experienced with the game,\n"
        'we recommend staying around 8, as turns can involve a variety of things\n'
        'and a high number here can consume alot of time.'
    ),
    'protection_turns': (
        'Turns Of Protection',
        'The number of turns of protection controls the number of turns for\n'
        'which a new empire is unable to attack, trade, and be attacked.  This\n'
        'is to allow small newcomers to join the game without immediately\n'
        'being destroyed.'
    ),
    'initial_land': (
        'Initial Market Land',
        'This option refers to the amount of land available to buy for a player\n'
        'at the beginning of the game.  Land is also created daily and a new\n'
        'player always has the option of buying up to 300 acres of land.  An\n'
        'initial value of 0 will give no advantage to the first few players,\n'
        'while a medium or high setting, depending on the number of turns per\n'
        'day, may be advantageous to the first players.'
    ),
    'land_per_day': (
        'Daily Land Creation',
        'This amount is the number of acres of land added to the market each day.\n'
        'The larger the value here, the faster growth the BBS is capable of.\n'
        'Smaller values will generally base strength more on attacks.'
    ),
    'wages': (
        'Standard Wages',
        'This amount refers to the number of silver coins a standard human worker is\n'
        'paid per month.  Lowering the value from the default will make people\n'
        'cheaper to hire, allowing players to devote less to money-making labor.\n'
        'This leads to faster growth rates, but make give larger empires a\n'
        'significant advantage.  The opposite is true of raising the cost of a\n'
        'worker.'
    ),
    'start_land': (
        'Starting Land',
        'This series of options allows you to control the start up settings of the\n'
        'players.  Using larger values tends will quicken the pace of the game,\n'
        'but may lead to some imbalances.  If you are not too experienced with the\n'
        'game, we highly recommend using the base settings.'
    ),
    'start_people': (
        'Starting People',
        'This series of options allows you to control the start up settings of the\n'
        'players.  Using larger values tends will quicken the pace of the game,\n'
        'but may lead to some imbalances.  If you are not too experienced with the\n'
        'game, we highly recommend using the base settings.'
    ),
    'start_silver': (
        'Starting Silver',
        'This series of options allows you to control the start up settings of the\n'
        'players.  Using larger values tends will quicken the pace of the game,\n'
        'but may lead to some imbalances.  If you are not too experienced with the\n'
        'game, we highly recommend using the base settings.'
    ),
    'start_food': (
        'Starting Food',
        'This series of options allows you to control the start up settings of the\n'
        'players.  Using larger values tends will quicken the pace of the game,\n'
        'but may lead to some imbalances.  If you are not too experienced with the\n'
        'game, we highly recommend using the base settings.'
    ),
    'start_stone': (
        'Starting Stone Blocks',
        'This series of options allows you to control the start up settings of the\n'
        'players.  Using larger values tends will quicken the pace of the game,\n'
        'but may lead to some imbalances.  If you are not too experienced with the\n'
        'game, we highly recommend using the base settings.'
    ),
    'start_weapons': (
        'Starting Weapons',
        'This series of options allows you to control the start up settings of the\n'
        'players.  Using larger values tends will quicken the pace of the game,\n'
        'but may lead to some imbalances.  If you are not too experienced with the\n'
        'game, we highly recommend using the base settings.'
    ),
    'start_runes': (
        'Starting Runes',
        'This series of options allows you to control the start up settings of the\n'
        'players.  Using larger values tends will quicken the pace of the game,\n'
        'but may lead to some imbalances.  If you are not too experienced with the\n'
        'game, we highly recommend using the base settings.'
    ),
    'max_attacks': (
        'Max Attacks',
        'This is the total number of attacks a player can make in one day.  It\n'
        'includes regular local attacks as well as both Individual and Group\n'
        'attacks in InterBBS games.  Because certain races have penalties in their\n'
        'attacks per day, this number should be set to at least 4, if not higher.'
    ),
    'max_spells': (
        'Max Spells',
        'This is the total number of spells a player can cast in one day.  It\n'
        'includes both local and InterBBS spells.  Because certain races have\n'
        'penalties in their spells per day, this number should be set to 5 at a\n'
        'minimum.  However, we recommend a higher setting such as 10 for creating\n'
        'a more interesting game.'
    ),
    'max_players': (
        'Maximum Players',
        'This setting determines the maximum number of players on a system.  The\n'
        'normal maximum is 25, but smaller leagues may wish to lower the value\n'
        'to distribute players more evenly.  Leagues consisting primarily of local\n'
        "BBS's may wish to use this option to make game play more competitive by\n"
        'dividing the players up.'
    ),
    'lost_attack_days': (
        'InterBBS: Lost Attack Prevention',
        'FE supports logging of attacks and lost attack prevention.  If an attack\n'
        'has not returned after a certain number of days, the forces will be\n'
        'returned to the owner and the attack voided.  If the attack is to return\n'
        'in the future, it will not be processed, pretending that the assault was\n'
        'never made.  The number of days should be kept a little bit larger than\n'
        'the maximum turn around time for attacks from one BBS to another.  League\n'
        'Coordinators, please be sure to take into consideration the maximum round\n'
        'trip time from any system in your league to any other, as the values you\n'
        'set will be used at all other systems in your league.'
    ),
    'local_attacks': (
        'InterBBS: Local Attacks',
        'This option enables or disables the ability to attack other local empires\n'
        'in Interplanetary games.  We highly recommend leaving this option enabled,\n'
        "forcing BBS's to use teamwork to remove troublemakers."
    ),
    'local_scoring': (
        'InterBBS: Local Attack Scoring',
        'Enabling this option in an Interplanetary game will make FE add score\n'
        'points to players who attack and defeat local opponents.  When disabled,\n'
        'score cannot be achieved through local fighting.  We recommend disabling\n'
        'this option, so that users cannot attack each other just to build up\n'
        'score.'
    ),
    'dupe_checking': (
        'InterBBS: Duplicate User Checking',
        'Enabling this feature will make FE look for users on your system that may\n'
        'be playing on other BBSes and temporarily lock them out of the game (until\n'
        "they delete one of their players).  In general, long-distance games don't\n"
        'require this option as much as local games may.  Leaving this feature OFF\n'
        'will save some data transferring, but allows players to play on several\n'
        'systems more easily.'
    ),
    'league_wide': (
        'InterBBS: League-Wide Reset',
        'Selecting this will send reset information to all other systems in the\n'
        'league, automatically resetting their games without sysop intervention.\n'
        'This can be used if you wish to end league play and restart the game\n'
        'fresh or if problems have developed requiring a league-wide reset.'
    ),
}
