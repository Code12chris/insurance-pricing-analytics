import pandas as pd
import sqlite3
import numpy as np
from scipy.stats import poisson
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import statsmodels.api as sm
import statsmodels.formula.api as smf
import seaborn as sns
import textwrap

#--------------------------------------------------------------------------------


#Plots nicht mehr anzeigen lassen -- interaktiver Modus ausgeschalten
plt.ioff()

#PDF-Datei initialisieren, für Abspeichern mehrerer Plots
pdf_pages = PdfPages('analyse_plots.pdf')



#Daten aus franz Datenbank laden
freq = pd.read_csv("data/freMTPL2freq.csv")
sev = pd.read_csv("data/freMTPL2sev.csv")

print("---CSV wurde geladen---")

#===============================================================================
#SQLite Datenbank erstellen
#===============================================================================


#Datenbank nun erstellen
connection = sqlite3.connect("insurance.db")


#Tabellen erstellen
freq.to_sql("policies", connection, if_exists="replace", index=False)
sev.to_sql("claims", connection, if_exists="replace", index=False)

print("---Tabellen erstellt---")

#===============================================================================
#Daten aus SQLite laden
#===============================================================================


policies = pd.read_sql_query("SELECT * FROM policies", connection)
claims = pd.read_sql_query("SELECT * FROM claims", connection)

connection.close()
print("---Daten aus SQLite geladen---")

#===============================================================================
#Erste Kontrolle des Ladens und korrekter Anzeige
#===============================================================================


print("---Tabellen-Daten werden angezeigt: ---")
print(policies.head())
print(claims.head())


print("---Tabellen-Dimensionen mit Zeilen, Spalten werden angezeigt: ---")
print(policies.shape)
print(claims.shape)


#===============================================================================
#Datenkonsistenz prüfen und Bestand bereinigen
#===============================================================================

"""
Frequenz (ClaimNb in policies) und Schadenhöhe (Zeilen in claims) müssen
dieselben Schäden beschreiben, sonst passen Frequenz x Schadenhöhe und die
beobachteten Schadenkosten nicht zusammen (Ursache der früheren
Portfolio-Abweichung von +31,9 %).

Prüfungen:
1. Schäden in claims ohne zugehörige Police
2. Policen, deren ClaimNb nicht zur Anzahl bezifferter Schäden passt
3. Datenblock am Anfang des Datensatzes: alle Policen bis zur ersten
   schadenfreien Police haben ClaimNb >= 1, aber kaum Schadenhöhen
"""

n_sev = claims.groupby("IDpol").size()
policies["n_sev"] = policies["IDpol"].map(n_sev).fillna(0).astype(int)

orphan_claims = ~claims["IDpol"].isin(policies["IDpol"])
inconsistent = policies["ClaimNb"] != policies["n_sev"]

# Block: alle Policen vor der ersten schadenfreien Police
block_end = policies.loc[policies["ClaimNb"] == 0, "IDpol"].min()
in_block = policies["IDpol"] < block_end

consistency = pd.DataFrame({
    "policies": [in_block.sum(), (~in_block).sum()],
    "exposure": [policies.loc[in_block, "Exposure"].sum(),
                 policies.loc[~in_block, "Exposure"].sum()],
    "ClaimNb": [policies.loc[in_block, "ClaimNb"].sum(),
                policies.loc[~in_block, "ClaimNb"].sum()],
    "claims_with_amount": [policies.loc[in_block, "n_sev"].sum(),
                           policies.loc[~in_block, "n_sev"].sum()]},
    index=[f"block IDpol < {block_end:.0f}", "rest of portfolio"])
consistency["share_with_amount"] = (consistency["claims_with_amount"]
                                    / consistency["ClaimNb"])
consistency["frequency"] = consistency["ClaimNb"] / consistency["exposure"]

print("\n--- Datenkonsistenz Frequenz vs. Schadenhöhe ---")
print(f"Summe ClaimNb: {policies['ClaimNb'].sum()} ; "
      f"Zeilen in claims: {len(claims)} ; "
      f"Verhältnis: {policies['ClaimNb'].sum() / len(claims):.3f}")
print(f"Schäden ohne Police: {orphan_claims.sum()}")

# Wie verteilen sich die Schäden ohne Police auf Policennummern?
orphan_by_id = (claims[orphan_claims].groupby("IDpol")["ClaimAmount"]
                .agg(claims="size", total="sum", largest="max")
                .sort_values("claims", ascending=False))
policy_ids = set(policies["IDpol"])
orphan_by_id["neighbours_in_policies"] = [
    (i - 1 in policy_ids) and (i + 1 in policy_ids) for i in orphan_by_id.index]
print(f"--> verteilt auf nur {len(orphan_by_id)} Policennummern:")
print(orphan_by_id.round(0))
print(f"zum Vergleich: Schäden je Police mit Schaden (zugeordnet): "
      f"{claims[~orphan_claims].groupby('IDpol').size().mean():.2f}")
print(f"Policen mit ClaimNb != Anzahl bezifferter Schäden: {inconsistent.sum()}")
print(consistency.round(4))

"""
Ergebnis: Fast alle nicht bezifferten Schäden liegen im Block am Anfang des
Datensatzes. Der Block enthält nur Schadenpolicen (ca. 1,3 % der Exposure,
aber ca. 27 % aller ClaimNb) mit unplausibler Jahresfrequenz von ca. 2.
Außerhalb des Blocks passen ClaimNb und bezifferte Schäden zu über 99,9 %.

Die 195 Schäden ohne Police gehören zu nur 6 Policennummern mit je 21-66
Schäden (normal: ca. 1,06 Schäden je Police mit Schaden). Die direkten
Nachbarnummern existieren jeweils in policies, es sind also Lücken im
Policenbestand. Alle 6 liegen im Nummernbereich 2.220.000-2.287.000, in dem
auch 5 der 8 Policen mit 5-16 Schäden liegen, darunter die mit nahezu
identischem Profil (Punkt 3 unten)
--> Hinweis auf Flotten bzw. Sammelverträge, die nicht als Einzelrisiken
im Datensatz abgebildet sind.

Bereinigung:
1. Block komplett ausschließen (ganze Policen). Nur die Schadenpolicen ohne
   Betrag zu streichen würde die Frequenz nach unten verzerren, weil die
   schadenfreien Policen erhalten blieben.
2. Übrige Policen mit ClaimNb != Anzahl bezifferter Schäden ausschließen.
3. Policen mit mehr als 4 Schäden ausschließen: wenige Policen mit bis zu
   16 Schäden bei teils < 0,1 Jahren Exposure und nahezu identischem Profil
   -> vermutlich Flotte oder Erfassungsfehler, kein Einzelrisiko.
   Ausschließen statt Kappen, damit ClaimNb und Schadenhöhen konsistent bleiben.
4. Exposure > 1 Jahr auf 1 kappen (Policen sind Jahresverträge).
5. Schäden ohne Police und Schäden ausgeschlossener Policen entfernen.
"""

keep = (~in_block) & (~inconsistent) & (policies["ClaimNb"] <= 4)

n_pol_raw, n_claims_raw = len(policies), len(claims)
amount_raw = claims["ClaimAmount"].sum()
n_exposure_capped = (policies.loc[keep, "Exposure"] > 1).sum()

policies = policies[keep].copy()
policies["Exposure"] = policies["Exposure"].clip(upper=1.0)
claims = claims[claims["IDpol"].isin(policies["IDpol"])].copy()

cleaning_summary = pd.DataFrame({
    "raw": [n_pol_raw, n_claims_raw, round(amount_raw)],
    "clean": [len(policies), len(claims), round(claims["ClaimAmount"].sum())]},
    index=["policies", "claims (rows with amount)", "total claim amount"])
cleaning_summary["removed_share_%"] = (
    (1 - cleaning_summary["clean"] / cleaning_summary["raw"]) * 100).round(2)

print("\n--- Bereinigung ---")
print(cleaning_summary)
print(f"Exposure auf 1 gekappt: {n_exposure_capped} Policen")
print(f"Konsistenz nach Bereinigung: Summe ClaimNb = {policies['ClaimNb'].sum()}, "
      f"Zeilen in claims = {len(claims)}")

assert policies["ClaimNb"].sum() == len(claims), "ClaimNb und Schadenzeilen inkonsistent"


#===============================================================================
#Struktur und Qualität der Daten prüfen
#===============================================================================



print(' --- Spalten im Policies-Datensatz ---')
print(policies.columns.tolist())


#Hier muss zwischen numerischen und kategorial(object) unterschieden werden
#damit GLM mit beiden Typen unterschiedlich arbeitet
print(' --- Datentypen ---')
print(policies.dtypes)


#Pflicht in Praxis fuer korrekte Modellnutzung, sonst Verzerrungen
#oder unbrauchbares Modell
print(' --- Fehlende Werte ---')
print(policies.isnull().sum())

#Statist. Begriffe anzeigen und bestimmen lassen u.a. quantile, mittelwert..
print(' --- Statistische Übersicht ---')
print(policies.describe())

#===============================================================================
#Analyse der Schadenfrequenz
#===============================================================================


print(' --- Verteilung der Schadenanzahl ---')
print(policies['ClaimNb'].value_counts().sort_index())


print(' --- Anteile in Prozent ---')
print((policies['ClaimNb'].value_counts(normalize=True).sort_index() * 100).round(2))


#-------------------------------------------------------------------------------
#Gesamtfrequenz pro Exposition
total_claims = policies['ClaimNb'].sum()
total_exposure = policies['Exposure'].sum()
frequency = total_claims / total_exposure
#-------------------------------------------------------------------------------


"""
Der Mittelwert von ClaimNb alleine ist nicht echte Schadenfreq., die muss hier
erst aus allen Claims und Exposure-Zeiträumen gemeinsam bestimmt werden.

Es muss noch auf Poisson-Verteilung geprüft werden.
"""

print(' --- Gesamtfrequenz ---')
print(f'Schäden gesamt: {total_claims}')
print(f'Exposure gesamt: {total_exposure:.2f}')
print(f'Jährliche Schadenfrequenz: {frequency:.4f}')


#===============================================================================
#Verifizieren der Poissonverteilung fuer Schadenanzahl
#===============================================================================

#-------------------------------------------------------------------------------
#Empirischer Mittelwert und Varianz bestimmen
mean_claims = policies['ClaimNb'].mean()
var_claims = policies['ClaimNb'].var()

print("---Mittelwert und Varianz von ClaimNb---")
print(f'Mittelwert ClaimNb: {mean_claims:.4f}')
print(f'Varianz ClaimNb: {var_claims:.4f}')
print(f'Varianz / Mittelwert: {var_claims/mean_claims:.2f}')
#-------------------------------------------------------------------------------

"""
Sollte Verhältnis von ca 1 eintreten, dann sehr gute Näherung an Poisson -->
Hier ergibt sich 1.08, also leichte Overdispersion.

Aber nicht stark verfälscht und damit fuer Poisson-GLM brauchbar
"""


#-------------------------------------------------------------------------------
#Beobachtete Anteile
obs = policies['ClaimNb'].value_counts(normalize=True).sort_index()


#Theoretische Poisson-Anteile mit gleichem Mittelwert
k = np.arange(0, 7)
theo = poisson.pmf(k, mean_claims)


#pdDataFrame siehe weiter unten Altersanalyse wegen Dokumentation
comparison = pd.DataFrame({ 'observed': obs.reindex(k, fill_value=0).values,
                            'poisson': theo })
comparison['difference'] = comparison['observed'] - comparison['poisson']

#-------------------------------------------------------------------------------


#Hier kommt ein grafischer Plot für den Vergleich

fig1, axes1 = plt.subplots(1, 2, figsize=(12,4))

# Linker plot - gesamtansicht
axes1[0].scatter(k, comparison['observed'], s=60, label='observed')
axes1[0].plot(k, comparison['poisson'], linestyle='--', color='red', label='poisson')

axes1[0].set_title('complete overview')
axes1[0].set_xlabel('number of claims(bins)')
axes1[0].set_ylabel('probability')
axes1[0].set_xticks(k)
axes1[0].grid(alpha=0.3)
axes1[0].legend()

# Rechter plot - zoom auf abweichungen
axes1[1].scatter(k, comparison['observed'], s=60, label='Beobachtet')
axes1[1].plot(k, comparison['poisson'], linestyle='--', color='red', label='Poisson')

axes1[1].set_title('zoom on rare damage events')
axes1[1].set_xlabel('number of claims(bins)')
axes1[1].set_ylabel('probability')
axes1[1].set_xticks(k)
axes1[1].set_ylim(0, 0.055)
axes1[1].grid(alpha=0.3)


plt.suptitle('comparison: empirical data vs. poisson distribution', fontsize=14)
plt.tight_layout()
pdf_pages.savefig(fig1,dpi=180)
plt.close(fig1)



#print('---Vergleich beobachtet vs. Poisson---')
#print(comparison.round(4))

"""
Die Tabelle 'comparison' soll theo. Werte von Poisson mit jähr. Schadenfreq. aus
den ClaimNb-Daten bewerten -->

Bei 0-Schäden etwas mehr, aber nahezu perfekt ; bei 1-Schäden weniger als erwartet ;
bei 2-Schäden etwas mehr als erwartet -->

Könnte auf leichte Heterogenität zwischen Risiken hinweisen
"""


#===============================================================================
#Heterogenität nach Fahreralter analysieren
#===============================================================================

#GroupBy von pandas.pydata.org fuer mehr Details zum Lesen
#pandas DataFrame dort auch gut dokumentiert

policies['age_group'] = pd.cut( policies['DrivAge'], bins=[17, 25, 40, 60, 100],
                                labels=['18-25', '26-40', '41-60', '61+'] )

age_analysis = ( policies .groupby('age_group', observed=True) .agg( contracts=('IDpol', 'count'),
                claims=('ClaimNb', 'sum'), exposure=('Exposure', 'sum') ) )

age_analysis['frequency'] = age_analysis['claims'] / age_analysis['exposure']

portfolio_frequency = total_claims / total_exposure

age_analysis['relativity'] = age_analysis['frequency'] / portfolio_frequency

print()
print(age_analysis.round(4))

#18-25 hat ca. doppelte Schadenfreq. (0.1487 / 0.0737 ~ 2.02) ;
#26-40 und 41-60 liegen nahe am Durchschnitt, 61+ ca. 17% darunter


#===============================================================================
# Heterogenität nach BonusMalus
#===============================================================================

policies['bm_group'] = pd.cut( policies['BonusMalus'], bins=[0, 50, 64, 80, 100, 125, 1000],
                                labels=['<=50', '51-64', '65-80', '81-100', '101-125', '>125'] )

bm_analysis = ( policies .groupby('bm_group', observed=True) .agg( contracts=('IDpol', 'count'),
                claims=('ClaimNb', 'sum'), exposure=('Exposure', 'sum') ) )
bm_analysis['frequency'] = bm_analysis['claims'] / bm_analysis['exposure']


#Relativität zum Portfoliodurchschnitt
portfolio_frequency = total_claims / total_exposure
bm_analysis['relativity'] = bm_analysis['frequency'] / portfolio_frequency


print()
print(bm_analysis.round(4))

"""
Gruppen mit bm > 100 liegen weit über dem Portfolio-Durchschnitt (Relativität
4.66 bzw. 5.94). Selbst im Vergleich zur Altersgruppe ist die Spannweite der
bm-Schadenfreq. deutlich größer, BM sollte also als Faktor mehr Einfluss haben.

Hohen bm über 100 haben wenig Verträge, man müsste tatsächlichen Einfluss noch
über weitere Analysen untersuchen(zb Konfidenzintervalle etc.)

Scheint Korrel. zwischen bm und tatsä. Risiko zu haben... Sollte man evtl.
noch stat. prüfen --> mit GLM testbar?
"""


#----------------------------------------------------------------------------------------

"""
in frankreich sind die Bonus-Malus anders als SF-Klassen gedacht:

BM 50 = 0.5 x praemie -- bester wert
...
BM 100 = 1.0 x pramie -- grundbeitrag ohne zu- und abschläge
BM 120 = 1.2 x pramie -- 20% zuschlag auf grundbeitrag

SF-Klassen ähnlich aber steigende Werte sind Reduzierung der Beiträge
und müssen separat gerechnet/modelliert sein
"""


#===============================================================================
# Datensatz fuer GLM vorbereiten
#===============================================================================

glm_data = policies.copy()

#nur positive Exposure verwenden
glm_data = glm_data[glm_data['Exposure'] > 0]

#fehlende Gruppen entfernen
glm_data = glm_data.dropna(subset=['age_group', 'bm_group'])

print()
print(glm_data.shape)


#===============================================================================
# Poisson-GLM nun erstellen
#===============================================================================

poisson_model = smf.glm( formula='ClaimNb ~ age_group + bm_group',
                data=glm_data, family=sm.families.Poisson(),
                offset=np.log(glm_data['Exposure']) ).fit()

print(poisson_model.summary())

#Hier ergeben sich nun erste analysen unter berücksichtigung beider merkmale
#alter und bm zusammen, die zu ungeahnten effekten führen können

"""
Pearson Chi2 / DF Residuals liegt über 1 (siehe Ausgabe).

Vorsicht bei der Interpretation: Bei sehr kleinen erwarteten Schadenzahlen
(kurze Exposure -> mu sehr klein) liefert ein einzelner Schaden einen riesigen
Beitrag (y - mu)^2 / mu. Der Wert wird daher stark von wenigen Policen mit
kurzer Exposure getrieben und ist kein verlässlicher Overdispersion-Test.
Ebenso ignoriert Varianz/Mittelwert = 1.08 von ClaimNb die unterschiedliche
Exposure. Overdispersion wird deshalb später über ein Negativ-Binomial-
bzw. Quasi-Poisson-Modell geprüft.
"""

pois_pearson_df = poisson_model.pearson_chi2 / poisson_model.df_resid
print(f"Poisson: Pearson Chi2 / df = {pois_pearson_df:.3f}")


"""
Bsp-Rechnung --- bm group '81-100' hat coef = 1.188 --> e**coef ~ 3.28 bzw. 228%
höhere Schadenfreq. als Fahrer mit bm <= 50 und gleichem Alter+Exposure
"""


#---------------------------------------------------------------------------------------
#Tariffaktoren aus dem GLM

tariffactors = pd.DataFrame({ 'coefficient': poisson_model.params,
                              'factor': np.exp(poisson_model.params) })

print(tariffactors.round(3))

"""
Kann coeff aus GLM in Faktoren mittels Expon. umrechnen, damit Faktoren zur
Tarifber. für z.B. Altersklassen und dazugehörigen BM-Klassen bei Police

Faktoren sind nun Parameter für Poisson, so z.B. Intercept von 0.046 für
jährliche Schadenfreq. der Referenzgruppe (18-25, bm <= 50)
== 4,6 Schäden / 100 Vertragsjahre

---------------------------------------------------------------------------

Bsp. Fahrer A ist in Altersgruppe 26-40 mit BM-Klasse 65-80...
Das GLM kann nun über Faktoren 0.046 x 0.815 x 2.375 ~ 0.089 zu
einer 8,9% erwarteten Schadenfreq. bestimmen.

Andere Faktoren bei anderen Zusammensetzungen berechnen sich analog
"""


"""
Fazit: Damit kann Modell Einfluss eines Merkmals bei konstant gehaltenen
anderen Merkmalen aufzeigen -- empirisch ist die Frequenz von bm '81-100'
0.1440 / 0.0512 ~ 2.81-mal so hoch wie bei bm <= 50, das GLM schätzt bei
gleichem Alter 3.28 (Alterseffekt herausgerechnet)

"""
#---------------------------------------------------------------------------



#Hier eine Heatmap zu den ergebnissen aus dem GLM für präsent.

# Erwartete Jahresfrequenzen aus dem GLM
# predict() auf einem DataFrame ignoriert den Offset (log(Exposure) = 0)
# und liefert damit direkt die Jahresfrequenz je Police. Ein zusätzliches
# Teilen durch Exposure wäre falsch und bläht die Werte auf.
heatmap_data = ( glm_data .assign(pred_freq = poisson_model.predict(glm_data))
                .groupby(['age_group', 'bm_group'], observed=True)['pred_freq']
                .mean() .unstack() )

fig2 = plt.figure(figsize=(8,4))
sns.heatmap( heatmap_data, annot=True, fmt='.3f', cmap='YlOrRd' )

plt.title('expected annual claim frequency from Poisson-GLM')
plt.xlabel('BonusMalus_group')
plt.ylabel('age_group')
pdf_pages.savefig(fig2, dpi=180)
plt.close(fig2)


#----------------------------------------------------------------------------

#===============================================================================
# explorative Analyse der Schadenhöhe
#===============================================================================

print("\n--- Schadenhöhen-Datensatz ---")
print("Anzahl Schäden:", len(claims))

print("\n--- Schadenhöhe ---")
print(claims["ClaimAmount"].describe())

"""
Schadenhöhe scheint rechtsschief zu sein, da mittelwert >> median ist.
Einige sehr große Schäden mit ca. 4 Mio auch deutlich höher als die
Quantile zu 50% oder 75% mit nur ca. 1200 ---> graf. Vert. untersuchen
"""

print("\n--- Fehlende Werte ---")
print(claims["ClaimAmount"].isnull().sum())

print("\n--- Kleinste Schadenhöhen ---")
print(claims["ClaimAmount"].nsmallest(10).values)

print("\n--- Größte Schadenhöhen ---")
print(claims["ClaimAmount"].nlargest(10).values)
print()



#===============================================================================
# explorative Analyse der Schadenhöhe
#===============================================================================



log_claims = np.log10(claims['ClaimAmount'])
fig3 = plt.figure(figsize=(8, 4))

plt.hist(log_claims, bins=60)
plt.title('distribution claim amount on logarithmic scale')
plt.xlabel('log10(claim amount in €)')
plt.ylabel('number of claims')
plt.tight_layout()
pdf_pages.savefig(fig3, dpi=180)
plt.close(fig3)


#der log plot sieht nahezu normalverteilt aus, so dass originale
#verteilung vermutlich lognormal verteilt ist


#===============================================================================
# Extremwerte auf Plausibilität pruefen
#===============================================================================

thresholds = [10000, 50000, 100000, 500000, 1000000]

for t in thresholds:
    count = (claims['ClaimAmount'] > t).sum()
    pct = count / len(claims) * 100
    print(f'>{t:>8,.0f} € : {count:5d} Schäden ({pct:.3f}%)')
    #f string mit rechtsbündig breite 8 ; ,als trennzeichen 1000er
    #.0f als null nachkommastellen; analog die anderen beiden

#es gibt sehr wenige große schäden (1 Mio und mehr)

print()
print('Top 20 Schäden:')
print(claims['ClaimAmount'].nlargest(20).round(0).to_list())

"""
3 Mio + fast 1 Mio - Werte: 4,1 Mio ; 1,4 Mio ; 1,3 Mio ; 0,77 Mio

Restliche Top 20 zwischen 200k und 400k, damit deutlich unterhalb schwerer Schäden ;
Sieht realist. aus, da vor allem 'nur 3' Mio-Schäden bei ca. 26000 Schäden gemeldet sind,
sprich viele Schäden typsich und sehr wenige Extremschäden;

Vllt auch falsche Daten gemeldet bei Extrema, andererseits mit 0.011% auch nur
extreme Ausreißer
"""


"""
Fazit: haben pos. Schadenhöhen ; (stark) rechtsschiefe Vert. Schadenhöhe ;
Nach log-Trafo nahezu normalverteilt --> lognormal-Vert. ? ;
Extremwerte sehr selten, wenn nicht fehlerhafte Daten

Erstmal Gamma-GLM probieren (standard) , dann wenn extremwerte zu stark
verzerren auf lognormal-modell wechseln

"""


#===============================================================================
#Severity-Datensatz aufbauen und Tariffaktoren betrachten
#===============================================================================

"""
Nun Schadenhöhe mit Datensatz genauer analysieren und neben Schadenfreq. für
zweite Säule berücksichtigen. Es werden nur pos. Schäden berücksichtigt

Nun Analyse welche Gruppe die schweren Schäden verursacht. Im ersten Teil
bei Poisson-GLM haben wir Freq. und die Gruppen untersucht, die höhere
Schadenhäufigkeit verursachten. Jetzt können wir prüfen, ob zb auch junge
Fahrer die teuren Schäden verursachen oder eine andere Gruppe.

Bspw. junge Fahrer: viele Schäden, aber meist günstiger ;
ältere Fahrer: seltener Schäden, aber meist teurer (kann, muss aber
nicht sein)
"""


# Severity-Datensatz erzeugen

severity_data = claims.merge( policies[['IDpol', 'age_group', 'bm_group']],
                on='IDpol', how='left' )

print(severity_data.shape)
print(severity_data.head())
print(severity_data[['ClaimAmount', 'age_group', 'bm_group']].describe())


#----------------------------------------------------------------------------

"""
Hier nochmal prüfen: Ob Anzahl Schäden, neg. Schadenhöhe und fehlende
ClaimAmount vorliegen --> 26065 (nach Bereinigung), 0, 0

Alles ok

print("Anzahl Schäden:", len(severity_data))
print("Schäden <= 0:", (severity_data["ClaimAmount"] <= 0).sum())
print("Fehlende ClaimAmount:", severity_data["ClaimAmount"].isna().sum())
"""

#----------------------------------------------------------------------------

#Datensatz Severity ausführen
severity = severity_data[severity_data["ClaimAmount"] > 0].copy()

print(severity.head())
print()

#Nach Altersgruppen anaylsieren und stat. Merkmale jeweils generieren

age_sev = severity.groupby("age_group")["ClaimAmount"].agg(
        n="count", mean="mean", median="median" ).round(2)

print(age_sev)
print()


#----------------------------------------------------------------------

#Altersgruppe 41-60 hat niedrigsten Mittelwert, berechne rel. Verhältnis
#dazu von anderen Mittelwerten für Vergleich


ref = age_sev.loc["41-60", "mean"]
age_rel = (age_sev["mean"] / ref).round(3)

print(age_rel)
print()

#----------------------------------------------------------------------

"""
Beobachtungen:

1. Mediane fast alle identisdch, dh typische Schäden in allen
Altersgruppen nahezu gleich


2. Mittelwerte unterscheiden sich aber stark, es sieht aktuell so aus,
dass junge Fahrer viel teure Schäden verursachen. Genauere Analysen
sollen zeigen, ob sich das bewahrheitet.

--> Rechte Tail wiegt schwer und zieht Mittelwert bei '18-25' massiv
nach oben

--> evtl nur wenige extreme Ausreißer in dieser Altersklasse, die
das verzerren oder system. höhere Schäden in diese Klasse üblich


Idee:

Verschiedene Quantile aufschlüsseln und beschreiben welche
Schadenssumme jeweils auftritt. Damit die Bereiche ident. die
für starke Verschiebung der Mittelwerte nach rechts verantwortlich
"""

#Hier Quantile aufbereiten von mittleren zu hohen Schäden

age_quant = severity.groupby("age_group")["ClaimAmount"].quantile(
            [0.5, 0.75, 0.90, 0.95, 0.99] ).unstack().round(2)

print('Claims nach alter in quantilen')
print(age_quant)
print()


"""
Bei Altersgruppe '18-25' steigt Schadenhöhe bei höherwerdenen Quantilen
im Vergleich zu älteren Gruppen immer stärker an.

Besonders starker Anstieg bei 99% Perzentil zu sehen.
"""

#tabelle zur rel Zunahme der Schadenhöhe

growth = age_quant.copy()

growth["75_vs_50"] = (growth[0.75] / growth[0.50]).round(2)
growth["90_vs_75"] = (growth[0.90] / growth[0.75]).round(2)
growth["95_vs_90"] = (growth[0.95] / growth[0.90]).round(2)
growth["99_vs_95"] = (growth[0.99] / growth[0.95]).round(2)


print('relativ zuwachs von quantil zu quantil nach alter')
print(growth[["75_vs_50", "90_vs_75", "95_vs_90", "99_vs_95"]])
print()

#-----------------------------------------------------------------
#plot der relativen Zuwächse

fig4, ax4 = plt.subplots(figsize=(8,4))

growth[["75_vs_50", "90_vs_75", "95_vs_90",
        "99_vs_95"]].plot( kind="bar", ax=ax4 )

plt.ylabel("relative growth")
plt.title("tail growth of claim amount sorted after age_group")
plt.xticks(rotation=0)
plt.tight_layout()
pdf_pages.savefig(fig4, dpi=180)
plt.close(fig4)


#-----------------------------------------------------------------

"""
Fazit: Typische Schäden (bis zu 90% Quantil) sind nahezu ident. bei
allen Altersgruppen. Bei großen Schäden (90%-95%) sind ähnliche Sprünge
zu sehen, aber Gruppe 18-25 etwas höher

Der Extreme Tail ab 95% nimmt enorm zu bei Gruppe 18-25 und auch ein
bisschen bei 61+. Aber vor allem 18-25 hat enorme Abweichung.

Mit dem tail_ratio sieht man die Zunahme deutlicher und ebenso mit
der Tabelle für rel. Zuwachs.

Der Mittelwert wird haupt. durch wenige sehr große Schäden nach oben
gezogen. Es sind also extreme Ausreißer bei jungen Fahrern, die
Mittelwert extrem nach oben treiben.
"""

#kennzahl um spannweite zu tail zu beziffern
tail_ratio = (age_quant[0.99] / age_quant[0.50]).round(1)
print(tail_ratio)

#-----------------------------------------------------------------

#Jetzt die BM-Klassen isoliert analysieren (wie bei Freq.)
bm_sev = severity.groupby("bm_group")["ClaimAmount"].agg(n="count",
        mean="mean", median="median").round(2)

print(bm_sev)
print()

"""
Beobachtung:

Mediane sind konstant, also typische Schadenhöhe unterscheidet sich
nicht durch BM-Klassen.


Mittelwerte unterscheiden sich deutlich:

'bm 101-125' -- 1845.76 vs. 'bm <= 50' -- 1912.37
vs. 'bm 81-100' -- 3863.00 vs. 'bm > 125' -- 3339.58

Tabelle zeigt, dass gerade im rechten Tail die Werte hoch sind
und Vermutung von früher stützen. Ausnahme hier 'bm 101-125' die
deutlich tiefer liegt.

--> nicht monotoner Zshg. zwischen BM-Klassem und Severity

Bemerkung: Bei 'bm > 125' gibt es nur 163 Schäden, also viel
weniger Daten und damit ein unsicherer/sensitiver Mittwert.
"""

#Quantile prüfen, um wieder Zuwächse zu studieren
bm_quant = severity.groupby("bm_group")["ClaimAmount"].quantile(
        [0.50, 0.75, 0.90, 0.95, 0.99]).unstack().round(2)

print(bm_quant)
print()

#Jetzt noch rel. Zuwächse bestimmen
bm_growth = bm_quant.copy()

bm_growth["75_vs_50"] = (bm_growth[0.75] / bm_growth[0.50]).round(2)
bm_growth["90_vs_75"] = (bm_growth[0.90] / bm_growth[0.75]).round(2)
bm_growth["95_vs_90"] = (bm_growth[0.95] / bm_growth[0.90]).round(2)
bm_growth["99_vs_95"] = (bm_growth[0.99] / bm_growth[0.95]).round(2)


print(bm_growth[["75_vs_50", "90_vs_75", "95_vs_90", "99_vs_95"]])
print()


"""
Beobachtung:

Bis zum 95% Quantil sind die Zuwächse bei den BM-Klassen(Ausnahme >125)
sehr ähnlich. Der Tail scheint auch hier extrem zu wirken.

Gerade im 99%-Quantil sind Zuwächse von x3.1 bis x4.1 und bei 'bm > 125'
sogar x6.72 aufgetreten. 


Aber auch hier wieder, es gibt bei höchsten BM-Klasse nur 163 Schäden, also
wieder Sensitivität mgl.
"""

#--------------------------------------------------------------------------

"""
Analyse bisher:

1. Typischer Schaden -- Alter und BM-Klassen unterscheiden sich kaum.

2. Erwartete Schadenhöhe -- Unterschiede vorhanden, teilweise sehr
verschiedene Reaktionen/Einfluss der Faktoren von zb Alter / BM

3. Gründe für Unterschiede -- Rechter Tail beeinflusst stast. Merkmale
deutlich

4. Extremgruppe -- sehr wenige Beobachtungen --> hohe Unsicherheit
"""

#-------------------------------------------------------------------------


#===============================================================================
#Gamma-GLM validieren und ergänzen
#===============================================================================

gamma_model = smf.glm(
    formula="ClaimAmount ~ age_group + bm_group",
    data=severity,
    family=sm.families.Gamma(link=sm.families.links.Log())
    ).fit()

print(gamma_model.summary())

#Früher wurden hier 195 Schäden ohne zugehörige Police vom Modell
#ausgeschlossen. Nach der Bereinigung (Abschnitt Datenkonsistenz) hat jeder
#Schaden eine Police --> Kontrolle, dass keine Merkmale fehlen:

#Fehlende Werte / Null-Daten aufspüren
print("Severity gesamt:", len(severity))

print(severity[["age_group", "bm_group"]].isna().sum())

print()
print(severity[severity[["age_group", "bm_group"]].isna()
        .any(axis=1)].head())
print()

"""
Ursprünglich fehlten für 195 Schäden age_group und bm_group, weil ihre
IDpol nicht in policies vorkommt. Diese Schäden werden jetzt bei der
Bereinigung entfernt, die Tabelle oben ist daher leer.
"""

#-------------------------------------------------------------------

"""
Nach dem Berechnen druch Gamma-GLM mit Referenzgruppe 18-25 & bm <= 50
sind die jungen Fahrer mit '18-25' die Gruppe mit höchster Severity.

Vgl. '26-40' haben 47,3% ; '41-60' hat 40,5% ; '61+' hat 51,4% im Bezug
zur Referenzgruppe mit ähnlichen Werten wie die deskrip. Analyse durch
empir. Mittelwerte

Achtung: Die drei Schäden über 1 Mio (4,08 Mio ; 1,40 Mio ; 1,30 Mio) gehören
alle zu Fahrern von 18-20 Jahren mit bm 100. Ohne sie läge die mittlere
Schadenhöhe von 18-25 bei ca. 2.300 statt ca. 5.100. Der hohe Severity-Faktor
junger Fahrer hängt also an drei Einzelschäden --> Großschadenbehandlung nötig.

BM-Klassen haben sehr geringe Koeffizienten und p-Werte (Annahme das jew.
Koeff. tatsächlich 0). Mit p < 0,05 statis. Signifikanz des Zshg und
Widerspruch gegen Nullhypothese. Hier aber alles über 0,13 (siehe
P >|z| in Tabelle)

"""

#---------------------------------------------------------------------------
#Jetzt nochmal den empir. Schaden mit Gamma vergleichen

severity_model = severity.dropna(subset=["age_group", "bm_group"]).copy()

severity_model["predicted"] = gamma_model.predict(severity_model)

compare = severity_model.groupby(["age_group", "bm_group"]).agg(
    n=("ClaimAmount", "count"),
    observed=("ClaimAmount", "mean"),
    predicted=("predicted", "mean")).round(2)

print('Tabelle severity model')
print(severity_model)


print('---Vergleich GLM vs. empirische Werte---')
print(compare)



"""
Beobachtung:

Das Modell kann höhere Severity bei 18-25 erkennen, kann aber
unterschied. Werte durch BM-Klassen kaum nachvollziehen. Da die
BM-Klassen im GLM nicht statist. signifikant waren --> logisch

Es gibt bei größeren Gruppen deutlich bessere Übereinstimmung.
Die extremen Abweichungen sind vor allem bei Gruppen mit sehr
wenig Schäden bspw. Alter '41-60' + 'bm >125' + '33' Schäden,
da dort beobach = 2449 vs. model = 1929

Die Kombination Alter '18-25' + 'bm 81-100' hat mit '1492' Schäden
große Stichprobe, das Modell schätzt hier sehr weit nach unten.
Grund: In dieser Zelle liegen alle drei Schäden über 1 Mio. Das Modell
verteilt deren Effekt über die Altersgruppe 18-25 und die bm-Klasse.


Vllt. sind Alter + BM-Klassen zu grobe Merkmale und es müssen für
Schadenhöhe noch Faktoren wie Fahrzeugtyp, Region usw. verwendet
werden. Also Unterschiede noch nicht gänzlich erklärt.
"""


#-----------------------------------------------------------------
#Jetzt Modellgüte prüfen

pearson_ratio = gamma_model.pearson_chi2 / gamma_model.df_resid
deviance_ratio = gamma_model.deviance / gamma_model.df_resid

print("Pearson / df:", pearson_ratio)
print("Deviance / df:", deviance_ratio)
print()

#Residuen plotten und bewerten

resid = gamma_model.resid_deviance
fig5 = plt.figure(figsize=(8, 5))
plt.hist(resid, bins=100)
plt.xlabel("deviance residuals")
plt.ylabel("count")
plt.title("deviance residuals of gamma-GLM")
pdf_pages.savefig(fig5, dpi=180)
plt.close(fig5)


fig6 = plt.figure(figsize=(8, 5))
plt.scatter(
    gamma_model.fittedvalues,
    gamma_model.resid_deviance,
    alpha=0.2
)
plt.xlabel("predicted claim amount")
plt.ylabel("deviance residuals")
plt.title("deviance residuals vs. predicted severity")
plt.axhline(0, linestyle="--")
pdf_pages.savefig(fig6, dpi=180)
plt.close(fig6)


#-----------------------------------------------------------------------------------
#Nochmal prüfen auf fehlerhafte Werte nach Log-Trafo

#Zeigt die logar. Schadenhöhen an und wichtige statis. Größen dazu
severity["log_claim"] = np.log(severity["ClaimAmount"])
print(severity["log_claim"].describe())

#Prüfen, ob Schadenhöhen '0' vorhanden, welche zu inf werden
print(np.isinf(severity["log_claim"]).sum())
print(severity["log_claim"].isna().sum())
print()
#Keine inf-Werte und damit keine Modifikation notwendig



#===============================================================================
#Lognormal-Modell prüfen und vorbereiten
#===============================================================================

#Lognormal-Modell ausgeführt für die beiden Merkmale Alter und BM wie bei
#Gamma-GLM zur besseren Vergleichbarkeit

lognormal_model = smf.ols(
    formula="log_claim ~ C(age_group) + C(bm_group)",
    data=severity).fit()

print(lognormal_model.summary())

"""
Beobachtung:

Referenzgruppe bei BM war <= 50 und im Vergleich dazu waren die anderen
BM-Klassen durch geringe p-Werte statist. signifikant. Ob dieses 'gute'
Abbilden des Merkmals nachher auch die Schadenhöhen im Vergleich zum
Gamma-GLM gut abschätzt muss später geprüft werden.
"""



#-----------------------------------------------------------------------------------
#Tabelle der Faktoren aus Log-Modell zur besseren Überischt zusammengefasst

coef_table = pd.DataFrame({
    "Coefficient": lognormal_model.params,
    "SeverityFactor": np.exp(lognormal_model.params)})

coef_table["PercentChange"] = (
    (coef_table["SeverityFactor"] - 1) * 100)

#Erster Einblick auf Severity-Faktoren aus dem Modell
print(coef_table.round(3))
print()


#Konfidenzintervalle der Severity-Faktoren aus Modell bestimmt,
#damit bessere Interpretation mgl

conf = lognormal_model.conf_int()
conf.columns = ["Lower", "Upper"]

severity_effects = pd.DataFrame({
    "Factor": np.exp(lognormal_model.params),
    "Lower95": np.exp(conf["Lower"]),
    "Upper95": np.exp(conf["Upper"])})


print(severity_effects.round(3))
print()

#----------------------------------------------------------------------------------
"""
In den nächsten Schritten word geprüft, wie sehr das Lognormal-Modell
die beobachteten Werte approx. und ob es damit ein besseres Modell
darstellt.

Es soll im Vgl. zum Gamma-GLM die Abweichungen geringer halten und die
Effekte der Extremschäden zumindest teilweise erfassen.
"""

# Vorhergesagte Werte auf der Log-Skala
severity["log_pred"] = lognormal_model.fittedvalues

# Residuen
severity["log_resid"] = lognormal_model.resid

print(severity[["log_claim", "log_pred", "log_resid"]].head())
print()

print(severity["log_resid"].describe())


#Plot zur Visualierung Residuen gegen vorhergesagte Werte
fig7=plt.figure(figsize=(8, 5))
plt.scatter(
    severity["log_pred"],
    severity["log_resid"],
    alpha=0.2,
    s=10)
plt.axhline(0, linestyle="--")
plt.xlabel("predicted log(claim amount)")
plt.ylabel("residuals")
plt.title("residuals vs. predicted values – lognormal-model")
pdf_pages.savefig(fig7, dpi=180)
plt.close()


"""
Beobachtung: Es gibt keinen erkennbaren Trend bspw Trichterform, die
ein systematisches Verhalten der Residuen erkennen lassen. Momentan gibt
es keinen Grund, dass das Modell besonders unpassend die Werte vorhersagt.
Es wird aber auch nicht eine große Güte bestätigt.
"""

#----------------------------------------------------------------------------------

#Histogramm der Residuen erstellen
#Kann von Glockenkurve abweichen, sollte aber annährend
#getroffen werden

fig8=plt.figure(figsize=(8, 5))
plt.hist(
    severity["log_resid"],
    bins=60)
plt.xlabel("residuals")
plt.ylabel("frequency")
plt.title("distribution of residuals – lognormal-model")
pdf_pages.savefig(fig8, dpi=180)
plt.close()

"""
Wieder eine annährende Normalverteilung, aber starke Häufung bei
0.5, vermutlich durch Bündelung von Kategorien wie Alter+BM-Klassen
"""


#----------------------------------------------------------------------------------

"""
Hier kommt der Q-Q-Plot(quantile-quantile-plot) zum Prüfen der
Normalverteilung der Residuen, idealerweise sollten die Punkte
ungefähr auf einer Diagonalen liegen.

Der extreme rechte Tail könnte für Ausreißer sorgen an den Rändern
des Q-Q-Plots.
"""


#print(severity["log_resid"].isna().sum())
#print(np.isinf(severity["log_resid"]).sum())
#Nach der Bereinigung gibt es keine NaN-Werte mehr,
#der Filter unten bleibt als Absicherung



#Nicht-endliche Werte vor Übergabe an Q-Q-Plot entfernen
#Q-Q-Plot erstellen

resid = severity["log_resid"]
resid = resid[np.isfinite(resid)]


fgqplot=sm.qqplot(
    resid,
    line="45",
    fit=True)
plt.title("q-q-plot of residuals – lognormal-model")
pdf_pages.savefig(fgqplot, dpi=180)
plt.close()

"""
Beobachtung: Der Plot verläuft entlang der Idealinie als
eine S-Kurve und zeigt damit Abweichungen auf. Es scheint
also eine systematische Abweichung von der Normalverteilung
zu geben, wobei die Stärke dieser Abweichungen noch nicht
feststeht.
"""



#----------------------------------------------------------------------------------

#Scale-Location-Plot für Streuung der Residuen prüfen
#Dafür Wurzel aus Residuen verwenden

fig9=plt.figure(figsize=(8, 5))
plt.scatter(
    severity["log_pred"],
    np.sqrt(np.abs(severity["log_resid"])),
    alpha=0.2,
    s=10)
plt.xlabel("predicted log(claim amount)")
plt.ylabel(r"$\sqrt{|residual|}$")
plt.title("scale-location-plot – lognormal-model")
pdf_pages.savefig(fig9, dpi=180)
plt.close()

"""
Auch hier wieder keinen Trend erkennbar wie z.B. die Trichterform.
Die Residuen haben ähnliche Werte egal bei welcher Schadenhöhe.
"""

"""
Fazit: Es gibt Abweichungen von Normalverteilung wie im Q-Q-Plot zu sehen.
Die Residuen scheinen auf keine besonderen Verzerrungen und falschen Fit
hinzudeuten.

Als nächstes sollten die beiden bisherigen Modelle Gamma-GLM und Lognormal
verglichen werden und das Tail-Verhalten bewertet werden (wo die größten
Probleme aufgetreten waren).
"""

#-----------------------------------------------------------------------------------


#===============================================================================
#Gamma- und Lognormal-Modell vergleichen und mit beobacht. Daten abgleichen
#===============================================================================

#Transformiere log-Werte zurück und führe Korrektur für erwarteten
#Schadenmittelwert mittels (sigma**2) / 2 aus = Bias-Korrektur

sigma2 = lognormal_model.mse_resid


#Erwartete Schadenhöhe auf Euro-Skala umrechnen
severity["lognormal_pred"] = np.exp(
    lognormal_model.fittedvalues + sigma2 / 2)

print(severity[["ClaimAmount", "lognormal_pred"]].head())
#Zwar zu hoch, aner wir haben noch keine Durschnittswerte
#betrachtet. Wir müssen aber diese vergleichen

# Gamma-Vorhersagen auf Euro-Skala
severity["gamma_pred"] = gamma_model.fittedvalues

# Beobachteter durchschnittlicher Schaden
observed_mean = severity["ClaimAmount"].mean()

# Durchschnittliche vorhergesagte Schadenhöhe
gamma_mean = severity["gamma_pred"].mean()

# Durchschnittliche vorhergesagte Schadenhöhe
lognormal_mean = severity["lognormal_pred"].mean()

print("Beobachteter Mittelwert:", observed_mean)
print("Gamma vorhergesagt:", gamma_mean)
print("Lognormal vorhergesagt:", lognormal_mean)

#----------------------------------------------------------------


#Vgl der beiden Modelle nach Altersgruppen

age_comparison = severity.groupby("age_group").agg(
    observed_mean=("ClaimAmount", "mean"),
    gamma_mean=("gamma_pred", "mean"),
    lognormal_mean=("lognormal_pred", "mean"),
    count=("ClaimAmount", "size")).round(2)

print(age_comparison)
print()

"""
Beim Vergleich der Altersgruppen ist Gamma-GLM
in jeder Gruppe die bessere Wahl und trifft alle
Gruppen ziemlich gut.

Das Lognormal-Modell scheint zu viele Gruppen zu
unterschätzen und eine Art 'Glättung' über alle
Gruppen hinweg vorzunehmen.
"""


#Vgl der beiden Modelle nach BM-Klassen

bm_comparison = severity.groupby("bm_group").agg(
    observed_mean=("ClaimAmount", "mean"),
    gamma_mean=("gamma_pred", "mean"),
    lognormal_mean=("lognormal_pred", "mean"),
    count=("ClaimAmount", "size")).round(2)

print(bm_comparison)
print()


"""
Ähnlich wie bei den Altersgruppen, kann Gamma-GLM
auch hier in jeder Gruppe die beobachteten Werte
deutlich besser treffen (Ausnahme BM 101-125).

Gamma ist also gegenüber Lognormal überlegen für
Schadenhöhe, auch wenn statist. Signifikanz von BM
durch Lognormal deutlicher rausgearbeitet wurde.

Fazit: Bessere statist. Signifikanz eines Merkmals
bedeutet nicht eine gute Approximation der
Schadenhöhe.

"""

#-----------------------------------------------------------------------------------
#Die beiden Vgl.-Tabellen in PDF gespeichert

#WMRAE vorab berechnen, damit die Plots den berechneten Wert zeigen
#(Definition und Interpretation weiter unten im Abschnitt Modellgüte)
def wmrae(comparison, pred_col="gamma_mean"):
    """Gewichteter mittlerer relativer absoluter Fehler in %,
    Gewicht = Anteil der Schäden je Gruppe, Fehler relativ zum beobachteten Mittel."""
    weights = comparison["count"] / comparison["count"].sum()
    rel_error = ((comparison[pred_col] - comparison["observed_mean"])
                 / comparison["observed_mean"]).abs()
    return (weights * rel_error).sum() * 100

age_wmrae = wmrae(age_comparison)
bm_wmrae = wmrae(bm_comparison)

wmrae_formula = (r"$WMRAE=\sum_g w_{g}\left|\frac{\hat{y}_{g}-y_{g}}{y_{g}}\right|$,"
                 r"  $w_g$ = share of claims, $y_g$ = observed mean")

#Altersgruppen-Vgl
fig10, ax = plt.subplots(figsize=(7, 2.5))
ax.axis("off")
table = ax.table(
    cellText=age_comparison.round(2).values,
    rowLabels=age_comparison.index,
    colLabels=age_comparison.columns,
    loc="center")

table.scale(1.2, 1.4)
fig10.text(
    0.02, 0.05,
    wmrae_formula + f"\nWMRAE Gamma (age groups) = {age_wmrae:.2f}%",
    fontsize=11
)

plt.title("model comparison by age_group")
pdf_pages.savefig(fig10, dpi=180, bbox_inches="tight")
plt.close()


#Altersgruppen-Vgl
fig11, ax = plt.subplots(figsize=(8, 3))
ax.axis("off")
table = ax.table(
    cellText=bm_comparison.round(2).values,
    rowLabels=bm_comparison.index,
    colLabels=bm_comparison.columns,
    loc="center")

table.scale(1.2, 1.4)
fig11.text(
    0.02, 0.05,
    wmrae_formula + f"\nWMRAE Gamma (Bonus-Malus groups) = {bm_wmrae:.2f}%",
    fontsize=11
)

plt.title("model comparison by bm_group")
pdf_pages.savefig(fig11, dpi=180, bbox_inches="tight")
plt.close()


#-----------------------------------------------------------------------------------

"""
Damit ist entschieden, dass Gamma-Modell als Basismodell
für die Schadenhöhe zu wählen.

Ob Gesamtmittel, Mittel nach Altersgruppen oder BM-Klassen
in jedem Bereich war Gamma immer näher an den beobachteten
Werten als Lognormal.

Der extreme Tail wurde in beiden Modellen zwar nicht gut
approx., aber die damit nach oben verzerrten Schaden-
mittelwerte von Gamma wieder besser erfasst als bei
Lognormal.
"""
#-----------------------------------------------------------------------------------

#===============================================================================
#Modellgüte des Gamma-GLM genauer untersuchen
#===============================================================================

#relative Abweichungen für jede Tarifgruppe betrachten

age_comparison["gamma_rel_error"] = (
    (age_comparison["gamma_mean"] - age_comparison["observed_mean"])
    / age_comparison["observed_mean"]
    * 100)

bm_comparison["gamma_rel_error"] = (
    (bm_comparison["gamma_mean"] - bm_comparison["observed_mean"])
    / bm_comparison["observed_mean"]
    * 100)

print("Altersgruppen:")
print(age_comparison)

"""
In allen Altersgruppen ist die proz. Abweichung kleiner als 6%, wobei
nur die junge Altersgruppe '18-25' unterschätzt wird mit -5,77%. Das
liegt an den drei Mio-Schäden in dieser Gruppe (Heavy Tail).

Insgesamt sehr gut getroffen und geringe Abweichungen.
"""


print("\nBM-Gruppen:")
print(bm_comparison)

"""
Bei den BM-Klassen werden die niedirgen BM-Klassen sehr gut getroffen,
wohingegen die höheren Klassen leider deutlich schlechter approx. werden.

Die drei höchsten Klassen weichen deutlich stärker ab, wobei nur die
Klasse '81-100' mit 4079 Beobachtungen ausreichend stark vertreten ist.
Für die anderen ergeben sich durch '101-125 = 1090 Beob.' und
'>125 = 163 Beob.' viel weniger Beobachtungen.

Daraus kann noch nicht auf ein schlechtes Modell geschlossen werden, da
diese Abweichungen durch mgl. Streuung bei zu wenigen Beobachtungen
verursacht werden kann.
"""

#-----------------------------------------------------------------------------------
"""
Jetzt betrachten wir eine Kennzahl, welche alle Abweichungen in beiden Tarifmerkmalen
und den Alters-/BM-Gruppen mit der Anzahl der Beobachtungen berücksichtigt

--> Weighted Mean Relative Absolute Error (WMRAE)
    = Anteil an Gesamtbeob. * rel. Gamma-Fehler

Das wird die relativen extremen Abweichungen bei den Gruppen mit wenigen Beobachtungen
bspw. 'BM > 125' mit 163 Beobachtungen besser beurteilen.

Durch die Absolubeträge heben sich Abweichungen pos. und neg. Tendenz nicht auf und
haben direkten Einfluss auf die "Gesamtabweichung".
"""

#WMRAE für Alters- und BM-Gruppen (oben mit wmrae() berechnet)

print(f"WMRAE Altersgruppen: {age_wmrae:.2f}%")
print()
print(f"WMRAE Bonus-Malus-Gruppen: {bm_wmrae:.2f}%")

"""
WMRAE für Altersgruppen ist 1.14%

Das ist eine sehr kleine Abweichung von den beobachteten
Schadenmittelwerten und damit eine sehr gute Kalibrierung
des Modells bzgl. der Altersgruppen.

---------------------------------------------------------
WMRAE für Bonus-Malus-Gruppen ist 3.11%

Das ist ebenfalls eine geringe Abweichung und deutlich
klarer zu verstehen, als die einzelnen großen Fehler bei
den hohen BM-Gruppen mit wenigen Beobachtungen.

---------------------------------------------------------
Schlussfolgerung:

Unter Berücksichtigung der Beobachtungsanzahlen der
einzelnen Tarifgruppen zeigen die gewichteten mittleren
relativen Fehler (WMRAE) bei beiden Gruppen sehr kleine
Abweichungen von den durchschnittlichen Schadenhöhen.

Das Gamma-GLM kann also sehr wohl die Tarifgruppen sehr
genau treffen und eignet sich daher als Severity-Modell.

Die zuvor gesehen Abweichungen und Fehler existieren zwar,
beeinflussen aber den 'Gesamtfehler' des Modells weniger
stark als zuvor vermutet.
"""

#-----------------------------------------------------------------------------------
#Erinnerung an Deviance und Pearson Chi**2 um mit oben
#gemachten Analysen Gesamtbild zu klären

deviance_ratio = gamma_model.deviance / gamma_model.df_resid
pearson_ratio = gamma_model.pearson_chi2 / gamma_model.df_resid

print(f"Deviance / df: {deviance_ratio:.2f}")
print(f"Pearson Chi² / df: {pearson_ratio:.2f}")

"""
Deviance / df = 1.64 und Pearson Chi2 / df = 47.34

Beim Gamma-GLM sind beide Werte keine Gütemaße, die man mit 1 vergleicht,
sondern Schätzer des Dispersionsparameters phi (Var = phi * mu^2).
Pearson Chi2 / df ist der Standardschätzer (= 'Scale' im Summary).

phi ~ 47 bedeutet einen Variationskoeffizienten von sqrt(47) ~ 6.9:
die Standardabweichung ist ca. 7-mal so groß wie der Erwartungswert.
Der große Unterschied zum Deviance-Schätzer zeigt, dass einige extreme
Schäden den Pearson-Schätzer dominieren --> Heavy Tail.

---------------------------------------------------------------------
Fazit:
Gamma-GLM erfasst die durschnittliche Schadenhöhe der Tarifgruppen
sehr gut, bildet aber die extreme Streuung der Schadenhöhenverteilung
nur eingeschränkt ab. Somit eine Modellgrenze identifiziert, die zur
Zeit nicht behoben werden kann.

In der Praxis müsste man nun komplexere Modelle/Ideen verwenden und
mittels weiterer Analysen den Tail besser beschreiben.
"""

#Güteanalyse damit vorerst abgeschlossen
#-----------------------------------------------------------------------------------

#===============================================================================
#Tarifstruktur konstruieren und Pure Premium bestimmen
#===============================================================================

#Umrechnung der Modellparameter in vorläufige Tariffaktoren
print("\nTarifrelativitäten Gamma GLM:")
for name, coef in gamma_model.params.items():
    factor = np.exp(coef)
    print(f"{name}: Faktor = {factor:.3f}")


#Alters- und BM-Tarife im Vergleich zur Referenzgruppe bestimmen

print("\nAlter:")
for group in severity["age_group"].dropna().unique():
    if group == "18-25":
        factor = 1.0
    else:
        factor = np.exp(gamma_model.params[f"age_group[T.{group}]"])
    print(f"{group}: {factor:.3f}")

print("\nBonus-Malus:")
for group in severity["bm_group"].dropna().unique():
    if group == "<=50":
        factor = 1.0
    else:
        factor = np.exp(gamma_model.params[f"bm_group[T.{group}]"])
    print(f"{group}: {factor:.3f}")

#-----------------------------------------------------------------------------------
#Erwartete Schadenhäufigkeit und Schadenhöhe bereitstellen

# Erwartete Schadenhäufigkeit (Poisson-GLM)
# predict() ohne Offset -> erwartete Jahresfrequenz (Exposure = 1)
policies["freq_pred"] = poisson_model.predict(policies)

# Erwartete Schadenhöhe (Gamma-GLM)
policies["sev_pred"] = gamma_model.predict(policies)


#Pure Premium berechnen --> jährliche Schadenkosten erhalten
policies["pure_premium"] = policies["freq_pred"] * policies["sev_pred"]


print(policies[["IDpol", "freq_pred", "sev_pred",
                "pure_premium"]].head())


#Jetzt die Alters- und BM-Gruppen in entsprechenden
#Tarifgruppen zusammengefasst

pricing_summary = (
    policies.groupby(["age_group", "bm_group"])
    .agg(
        policies=("IDpol", "count"),
        freq_pred=("freq_pred", "first"),
        sev_pred=("sev_pred", "first"),
        pure_premium=("pure_premium", "first"))
    .round(2))

print(pricing_summary)

#-----------------------------------------------------------------------------------

#Visualisierungen zum Tarif erstellen
#1. Heatmap
#2. Balkendiag. für Vergleich


pure_premium_matrix = pricing_summary["pure_premium"].unstack()

fig12, ax = plt.subplots(figsize=(8, 5))
im = ax.imshow(pure_premium_matrix.values, aspect="auto", cmap="YlOrRd")

ax.set_xticks(range(len(pure_premium_matrix.columns)))
ax.set_xticklabels(pure_premium_matrix.columns)

ax.set_yticks(range(len(pure_premium_matrix.index)))
ax.set_yticklabels(pure_premium_matrix.index)

ax.set_xlabel("Bonus-Malus group")
ax.set_ylabel("age group")
ax.set_title("expected pure premium (€) by tariff class")

# Werte in die Heatmap schreiben
for i in range(pure_premium_matrix.shape[0]):
    for j in range(pure_premium_matrix.shape[1]):
        ax.text(
            j, i,
            f"{pure_premium_matrix.iloc[i, j]:.0f}",
            ha="center",
            va="center",
            fontsize=8)

fig12.colorbar(im, ax=ax, label="pure premium (€)")
plt.savefig("pure_premium_heatmap.png", dpi=200, bbox_inches="tight")
pdf_pages.savefig(fig12, dpi=180)

plt.close()


#Balkendiagramm der Pure Premium
plot_data = pricing_summary.reset_index()

age_groups = ["18-25", "26-40", "41-60", "61+"]
bm_order = ["<=50", "51-64", "65-80", "81-100", "101-125", ">125"]

fig13, axes = plt.subplots(2, 2, figsize=(12, 8), sharey=True)
axes = axes.flatten()

for ax, age in zip(axes, age_groups):
    subset = plot_data[plot_data["age_group"] == age].copy()
    subset["bm_group"] = subset["bm_group"].astype(str)
    subset = subset.set_index("bm_group").loc[bm_order].reset_index()

    ax.bar(
        ["BM " + bm for bm in subset["bm_group"]],
        subset["pure_premium"])

    ax.set_title(f"age {age}")
    ax.set_xlabel("Bonus-Malus group")
    ax.tick_params(axis="x", rotation=30, labelsize=8)

axes[0].set_ylabel("pure premium (€)")
axes[2].set_ylabel("pure premium (€)")

fig13.suptitle("expected pure premium by age group and Bonus-Malus group",
            fontsize=14)
plt.tight_layout()


pdf_pages.savefig(fig13, dpi=180, bbox_inches="tight")
plt.close()

#-----------------------------------------------------------------------------------
#===============================================================================
#Tarifstruktur konstruieren und Pure Premium bestimmen
#===============================================================================

"""
Pure-Premium-Plausibilität prüfen über Vgl. mit beobachteten Schaden und
Exposure aus Daten. Jetzt können wir ein erstes Mal Brauchbarkeit der
Modelle testen, durch die Abweichungen zu den erbrachten Leistungen.
"""

#Berechnet für jeweiligen Gruppen die Summe der Claims
observed_cost = (severity_data.groupby(["age_group", "bm_group"])
                .agg(observed_claim_amount=("ClaimAmount", "sum")))


#Berechnet für die Gruppen jeweils die Exposure
observed_exposure = (policies.groupby(["age_group", "bm_group"])
                .agg(exposure=("Exposure", "sum")))

#Zusammenführen für Bestummung der jährlichen Schadenskosten
observed_pricing = observed_exposure.join(observed_cost)


#Berechnung jährlicher Schadenskosten pro Police

observed_pricing["observed_pure_premium"] = (
    observed_pricing["observed_claim_amount"]
    / observed_pricing["exposure"])



#Erstellen der finalen Table für Vgl. und Abweichungen
pricing_check = pricing_summary.join(
    observed_pricing["observed_pure_premium"])


#Relative Abweichungen in Table aufnehmen
pricing_check["relative_error"] = (
    (pricing_check["pure_premium"] - pricing_check["observed_pure_premium"])
    / pricing_check["observed_pure_premium"]* 100).round(2)

print()
print(pricing_check.round(2))

"""
Beobachtung:

Es gibt bei den einzelnen Gruppierungen deutliche Abweichungen so z.B.
bei Alter '18-25' und BM '51-64' --> +283% zu beobachteten jährlichen
Schadenkosten. Wohingegen selbe Altersgruppe mit BM '>125' --> -27%
Abweichung hat. Die Abweichungen in 18-25 kommen vor allem daher, dass die
drei Mio-Schäden über den Alters-Faktor auf alle BM-Klassen verteilt werden.

Wie bereits bemerkt gibt es durch wenige Extremschäden große Schwankungen
bzw. Verzerrungen. Das Modell scheint system. Zusammenhänge abbzubilden,
aber auch eine Glättung vorzunehmen.

Es wäre also besser wie bei der Güte vom Gamma-GLM eine Gewichtung der
einzelnen Gruppen zu machen und die Exposure als Gewicht einzurechnen.

Das geschieht im nächsten Code-Abschnitt.
"""


#Gewichtung durch Exposure berücksichtigen
pricing_check["exposure"] = observed_pricing["exposure"]

weighted_error = (pricing_check["exposure"]
    * pricing_check["relative_error"].abs()
).sum() / pricing_check["exposure"].sum()

print(f"Exposure-weighted absolute relative error:{weighted_error:.2f}%")

"""
Diese Kennzahl für Abweichung mit Gewichtung durch Exposure liegt bei 11,61%
(vor der Datenbereinigung 49,80%) und wird durch hohe Abweichungen einiger
kleiner Gruppen getrieben.

Die Kennzahl reagiert empfindlich auf die hohen ClaimAmounts, welche auf
individueller Ebene einzelne Gruppierungen nach oben treiben.

Diese Kennzahl ist also nur ein erster Check für Plausibilität von
Tarifzahlen, bewertet aber nicht den Gesamtfit für das Portfolio. Das
wird weiter unten in den nächsten Code-Zeilen geschehen, womit dann die
Bewertung der gesamten Struktur die Güte der Tarifierung aufzeigt.
"""

#Portfolio Validierung in einer Table aufbereiten

"""
Jede Police hat eine unterschiedliche Exposure und kann nicht gemeinsam
gemittelt werden, d.h. jede Police muss mit ihrer eigenen Exposure gewichtet
werden und dann später durch die Gesamtexposure geteilt werden.
"""

#Exposure für gesamtes Portfolio auf Nomiertheit (=1) prüfen
print(policies["Exposure"].describe())
print(policies["Exposure"].mean())

#Hier ist eine Mean-Exposure von ca 0.53 zu sehen, was nochmals das
#Gewichten bestätigt



"""
Hier werden jetzt die beobachteten Claims mit dem Modell-Pure-Premium
verglichen und ein relativer Fehler dazu bestimmt. Das soll dann die
Validierung des gesamten Portfolios darstellen.
"""

#Beobachtete Claim für Table vorbereiten
observed_portfolio = (
    severity_data["ClaimAmount"].sum()
    / policies["Exposure"].sum())


modeled_portfolio = (
    (policies["pure_premium"] * policies["Exposure"]).sum()
    / policies["Exposure"].sum())


portfolio_error = (
    (modeled_portfolio - observed_portfolio)
    / observed_portfolio * 100)


#Table nun erstellt und ausgegeben
validation_table = pd.DataFrame({
    "Metric": [
        "Observed portfolio claim cost (€)",
        "Modeled portfolio pure premium (€)",
        "Portfolio relative error (%)",
        "Exposure-weighted tariff-class error (%)"],
    "Value": [
        round(observed_portfolio, 2),
        round(modeled_portfolio, 2),
        round(portfolio_error, 2),
        round(weighted_error, 2)]})

print("\nPortfolio validation:")
print(validation_table)


"""
Beobachtung:

Observed = 167,15 ; beobachteter Schadenaufwand pro Versicherungsjahr

Model Pure Premium = 165,82 ; modellierter Schadenaufwand pro Versicherungsjahr

Portfolio rel. Fehler = -0,79%

Weighted Error = 11,61% ;
Stellt die durchschnittliche absolute Abweichung der 24 Tarifklassen nach Exposure
gewichtet da. Wird durch einzelne verzerrte Tarifklassen stark beeinflusst.

------------------------------------------------------------------------------
Fazit:

Vor der Datenbereinigung lag der Portfolio-Fehler bei +31,91%. Ursache war nicht
die Exposure, sondern die Daten: Der Block am Anfang des Datensatzes enthält ca.
27% aller ClaimNb, aber fast keine Schadenhöhen. Die Frequenz kam aus ClaimNb,
der beobachtete Aufwand nur aus bezifferten Schäden --> Überschätzung um ca.
ClaimNb / bezifferte Schäden ~ 1,35.

Die -0,79% sind KEIN Nachweis guter Prognosequalität: Das Poisson-GLM mit
Log-Link reproduziert in-sample die Schadenzahl exakt, das Gamma-GLM die
Schadensumme fast exakt. Die Kennzahl zeigt nur, dass Frequenz- und
Schadenhöhendaten jetzt konsistent sind. Die Prognosegüte muss out-of-sample
(Train/Test-Split) geprüft werden.
"""






#-----------------------------------------------------------------------------------
#Speichert die Plots in einer PDF ab und steht im Ordner zur Verfügung

pdf_pages.close()
print('PDF mit allen Plots gespeichert')
