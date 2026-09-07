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
pdf_pages.savefig(fig1)
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

#Für 19-25 ist 74% höhere Schadenfreq., da 0.1751/1007 ~ 1.74 und damit
#stark über Durchschnitt von 10.07% ; anderen Gruppen höchs. 7% Abweichung


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
Gruppe mir bm>100 ist prozent. viel höher als im Portfolio-Durschschnitt mit 4.37
selbsz im Vergleich zur Altersgruppe ist bm-Schadenfreq. deutlich größer, sollte
also als Faktor einen viel höheren Einflus haben.

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
Mit Pearson Chi2 ~ 2.02e+06 und DF Residuals = 678004 kann Deviance-Verhältnis 
mittels Chi2/(DF Resid.) ~ 2.98 bestimmt werden --> deutl. Overdispersion,
ideal wäre rund 1 gewesen.

Berücksicht. von Alter und BonusMalus zeigt im Gegensatz zu Gesamtvert. von
Claims (1.08 Deviance) deutl. Overdispersion --> exit unbeob. Heterogenität
mit mgl anderen Ursachen evtl. Region, Bevölkerungsdichte etc.

-->Ergänzung um weitere Variablen mgl oder auf neg. Binomial wechseln

Beruecksichtung von Alter und BonusMalus zeigt anders als bei gesamtverteil.
claims(1.08 deviance) deutliche overdsipersion --> unbeobachtete heterogenitaet
mit mgl anderen ursachen evtl region, bevoelkerungsdichte etc.
"""


"""
Bsp-Rechnung --- bm group '81-100' hat coef = 0.9590 --> e**coef ~ 2.61 bzw. 161% 
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

Faktoren sind nun Parameter für Poisson, so z.B. Intercept von 0.070 für
jährliche Schadenfreq. der Referenzgruppe == 7 Schäden / 100 Vertragsjahre

---------------------------------------------------------------------------

Bsp. Fahrer A ist in Altersgruppe 26-40 mit BM-Klasse 65-80...
Das GLM kann nun über Faktoren 0.070 x 0.845 x 1.844 ~ 0.109 zu 
einer 10,9% erwarteten Schadenfreq. bestimmen.

Andere Faktoren bei anderen Zusammensetzungen berechnen sich analog
"""


"""
Fazit: Damit kann Modell Einfluss eines Merkmals bei konstant gehaltenen
anderen Merkmalen aufzeigen -- aus empir. Ber. hatten wir 1.77 vs. nun
bestimmten 2.61

"""
#---------------------------------------------------------------------------



#Hier eine Heatmap zu den ergebnissen aus dem GLM für präsent.

# Erwartete Frequenzen aus dem GLM
heatmap_data = ( glm_data .assign(pred_freq = poisson_model.predict(glm_data) / 
                glm_data['Exposure']) .groupby(['age_group', 'bm_group'],
                 observed=True)['pred_freq'] .mean() .unstack() )

fig2 = plt.figure(figsize=(8,4))
sns.heatmap( heatmap_data, annot=True, fmt='.3f', cmap='YlOrRd' )

plt.title('expected claims frequency from Poisson-GLM')
plt.xlabel('BonusMalus_group')
plt.ylabel('age_group')
pdf_pages.savefig(fig2)
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
Quantile zu 50% oder 75% mit nur 1222 ---> graf. Vert. untersuchen
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
pdf_pages.savefig(fig3)
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
Sieht realist. aus, da vor allem 'nur 3' Mio-Schäden bei 27000 Schäden gemeldet sind,
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
ClaimAmount vorliegen --> 26639, 0, 0

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
pdf_pages.savefig(fig4)
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

'bm 101-125' -- 1844.08 vs. 'bm <= 50' -- 1922.22 
vs. 'bm > 125' -- 3339.58

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

Gerade im 99%-Quantil sind Zuwächse von x3 , x4.11 und bei 'bm > 125'sogar
x6.72 aufgetreten. 


Aber auch hier wieder, es gibt bei höchsten BM-Klasse nur 162 Schäden, also
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
    family=sm.families.Gamma(link=sm.families.links.log())
    ).fit()

print(gamma_model.summary())

#Im Modell wurden 195 Schäden rausgerechnet, kann an fehlenden Einträgen
#in Daten bspw bm oder age_group liegen --> aufklären...

#Fehlende Werte / Null-Daten aufspüren
print("Severity gesamt:", len(severity))

print(severity[["age_group", "bm_group"]].isna().sum())

print()
print(severity[severity[["age_group", "bm_group"]].isna()
        .any(axis=1)].head())
print()

"""
Die letzte Tabelle zeigt, dass 195 Verträge für age_group und
bm_group nicht vorhanden sind. Es ist jetzt unklar, warum diese
Verträge keine Merkmale haben.

Aber da 195/26639 ~ 0.73% einen kleinen Teil ausmachen, kann man
erstmal ohne weitermachen, was statsmodels im GLM autom. gemacht hat
"""

#-------------------------------------------------------------------

"""
Nach dem Berechnen druch Gamma-GLM mit Referenzgruppe 18-25 & bm <= 50
sind die jungen Fahrer mit '18-25' die Gruppe mit höchster Severity.

Vgl. '26-40' haben 47,4% ; '41-60' hat 40,8% ; '61+' hat 51,3% im Bezug
zur Referenzgruppe mit ähnlichen Werten wie die deskrip. Analyse durch
empir. Mittelwerte

BM-Klassen haben sehr geringe Koeffizienten und p-Werte (Annahme das jew.
Koeff. tatsächlich 0). Mit p < 0,05 statis. Signifikanz des Zshg und 
Widerspruch gegen Nullhypothese. Hier aber alles über 0,231 (siehe
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
da dort beobach = 2449 vs. model = 1942

Die Kombination Alter '18-25' + 'bm 81-100' hat mit '1498' Schäden
große Stichprobe, das Modell schätzt hier sehr weit nach unten.
Das ist eine besondere Ausnahme und zeigt Probleme auf, beim 
vollständigen Erfassen der kompl. Struktur


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
pdf_pages.savefig(fig5)
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
pdf_pages.savefig(fig6)
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
pdf_pages.savefig(fig7)
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
pdf_pages.savefig(fig8)
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
#Es gibt 195 NaN-Werte die vom Modell ausgeschlossen wurden,
#aber im DataFrame noch enthalten sind



#Entferne 195 NaN-Werte vor Übergabe an Q-Q-Plot
#Q-Q-Plot erstellen

resid = severity["log_resid"]
resid = resid[np.isfinite(resid)]


fgqplot=sm.qqplot(
    resid,
    line="45",
    fit=True)
plt.title("q-q-plot of residuals – lognormal-model")
pdf_pages.savefig(fgqplot)
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
pdf_pages.savefig(fig9)
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
    r"$WMRAE=\sum w_{g}\left|\frac{y_{g}-y_{o}}{y_{g}}\right|$"
    "\nWMRAE (Age Groups) = 1.13%",
    fontsize=11
)

plt.title("model comparison by age_group")
pdf_pages.savefig(fig10, dpi=300, bbox_inches="tight")
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
    r"$WMRAE=\sum w_{g}\left|\frac{y_{g}-y_{o}}{y_{g}}\right|$"
    "\nWMRAE (Bonus-Malus Groups) = 3.06%",
    fontsize=11
)

plt.title("model comparison by bm_group")
pdf_pages.savefig(fig11, dpi=300, bbox_inches="tight")
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
nur die junge Altersgruppe '18-25' unterschätzt wird mit -5,75%. Das 
kann man vermutlich auf den Heavy-Tail zurückführen.

Insgesamt sehr gut getroffen und geringe Abweichungen.
"""


print("\nBM-Gruppen:")
print(bm_comparison)

"""
Bei den BM-Klassen werden die niedirgen BM-Klassen sehr gut getroffen,
wohingegen die höheren Klassen leider deutlich schlechter approx. werden.

Die drei höchsten Klassen weichen deutlich stärker ab, wobei nur die 
Klasse '81-100' mit 4106 Beobachtungen ausreichend stark vertreten ist.
Für die anderen ergeben sich durch '101-125 = 1093 Beob.' und
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

#WMRAE für Alters- und BM-Gruppen berechnen

age_wmrae = (
    (age_comparison["count"] / age_comparison["count"].sum())
    * age_comparison["gamma_rel_error"].abs()).sum()

bm_wmrae = (
    (bm_comparison["count"] / bm_comparison["count"].sum())
    * bm_comparison["gamma_rel_error"].abs()).sum()

print(f"WMRAE Altersgruppen: {age_wmrae:.2f}%")
print()
print(f"WMRAE Bonus-Malus-Gruppen: {bm_wmrae:.2f}%")

"""
WMRAE für Altersgruppen ist 1.13%

Das ist eine sehr kleine Abweichung von den beobachteten 
Schadenmittelwerten und damit eine sehr gute Kalibrierung
des Modells bzgl. der Altersgruppen.

---------------------------------------------------------
WMRAE für Bonus-Malus-Gruppen ist 3.06%

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
Deviance = 1.65
--> ist gering genug, um Gamma als brauchbar für das systematische
Erfassen der Daten zu bewerten.


Pearson = 46.99
--> ist sehr hoch und spricht für eine große Streuung. Der Heavy Tail
wird also durch Gamma nicht komplett abbgebildet.

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
#Tarifstruktur konstruieren und Übergang zum Pure Premium vorbereiten
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
#Speichert die Plots in einer PDF ab und steht im Ordner zur Verfügung

pdf_pages.close()
print('PDF mit allen Plots gespeichert')

