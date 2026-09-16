# Points to raise with Gordon

Working list for espruino#8013. Everything came out of implementing the design.
Ordered by how much it needs an answer. Last checked 2026-09-16.

> **FR —** Liste de travail pour la discussion espruino#8013. Tout ce qui suit
> est sorti de l'implémentation réelle du protocole. Classé par besoin de
> réponse décroissant. Dernière vérification : 16-09-2026.
>
> *Chaque section anglaise est suivie de sa traduction dans un bloc comme
> celui-ci. L'anglais reste le texte à transmettre à Gordon.*

---

## 1. Master builds advertise service data with no UUID

Not a BTHome question, and the most urgent thing here. On a `2v29.242` build,
`NRF.setAdvertising` emits the service-data AD structure **without its 16-bit
UUID**. The changelog entry is in the unreleased section:

> BLE: switch to our own code for creating advertisement packets (shared across
> all platforms).

A standard UUID with nothing to do with this project makes the point:

```
NRF.getAdvertisingData({0x180F:[1,2,3]}, {showName:false})
  got       02 01 06 04 16 01 02 03
  expected  02 01 06 06 16 0f 18 01 02 03
```

Every key spelling behaves the same — `0xFCD2`, `"FCD2"`, `64722`, `0x180F`. On
the air, a nice!nano's BTHome payload begins where `d2 fc` should be, so
receivers file it under UUID `0x0040` and no BTHome install will ever match it.
A Puck.js on a release build is unaffected.

The raw AD-structure form still works, and is our workaround if this is
intended:

```
NRF.setAdvertising([2,1,6, 13,0x16,0xd2,0xfc, ...payload], {showName:false})
  ->  02 01 06 0d 16 d2 fc 40 00 77 02 f0 0a 53 00 ff 04
```

Same builds also stopped shortening the local name to make a packet fit — they
refuse the packet instead. Nothing found in the issues, discussions or forum, so
this looks unreported. Full measurements in `decisions.md` D-046.

> **FR — Les builds de master émettent du service data sans UUID.**
>
> Ce n'est pas une question BTHome, et c'est le point le plus urgent du
> document. Sur un firmware `2v29.242`, `NRF.setAdvertising` produit la
> structure de service data **sans son UUID 16 bits**. L'entrée de changelog
> correspondante est dans la section non publiée : « BLE: switch to our own code
> for creating advertisement packets » — Gordon a réécrit le constructeur de
> paquets d'advertising, partagé entre toutes les plateformes.
>
> L'exemple choisi utilise `0x180F`, un UUID standard sans aucun rapport avec ce
> projet : on attend `06 16 0f 18 01 02 03`, on obtient `04 16 01 02 03`. Toutes
> les orthographes de clé donnent le même résultat. Sur l'air, la charge BTHome
> d'un nice!nano commence là où `d2 fc` devrait être, donc les récepteurs
> classent l'appareil sous l'UUID `0x0040` et aucune installation BTHome ne le
> reconnaîtra jamais. Un Puck.js sur une version publiée n'est pas touché.
>
> La forme brute de `setAdvertising` fonctionne encore : c'est notre
> contournement si ce comportement est volontaire. Ces mêmes builds ont aussi
> cessé de raccourcir le nom local pour faire tenir un paquet — ils refusent le
> paquet à la place. Rien trouvé dans les issues, discussions ou forum : cela
> semble non signalé. Mesures complètes dans `decisions.md` D-046.

---

## 2. The `BTHome` module fixes are not published

You fixed both on 2026-09-10 and EspruinoDocs master has them:

```js
illuminance : e => b24(5, e, 100),
humidity    : e => [0x2E, Math.round(e.v)],
```

`https://www.espruino.com/modules/BTHome.js` still serves the old file — no
`illuminance`, and `humidity : e => [0x2E, e, 1]`, which pushes the entry object
where it means to push the value. That URL is what the Web IDE and every
deployment tool fetch from, so devices still get the broken one and this repo's
example still goes through `raw`.

> **FR — Les correctifs du module `BTHome` ne sont pas publiés.**
>
> Gordon a corrigé les deux le 10-09-2026 et EspruinoDocs master les contient
> bien. Mais `https://www.espruino.com/modules/BTHome.js` sert toujours
> l'ancienne version : pas d'`illuminance`, et un `humidity` qui empile l'objet
> d'entrée là où il devrait empiler la valeur. Or c'est précisément de cette URL
> que le Web IDE et tous les outils de déploiement téléchargent. Les appareils
> reçoivent donc encore la version cassée, et l'exemple de ce dépôt doit
> continuer à passer par l'échappatoire `raw`.

---

## 3. Write-only, for fixed-length objects — needs your agreement

Settled on the device side: an entry with `set` and no `get` is write-only, and
the module advertises it back at zero length (D-009).

Open for **fixed-length** objects, where "advertise it with an empty value" has
no representation — an object ID with no value bytes is not something a BTHome
parser can walk. A light that is off advertises `1E 00`, byte-identical to a
placeholder, so a receiver cannot tell a stateless trigger from an actuator that
happens to be off. Guessing wrong means either exposing a real switch as
stateless, or waiting forever for a confirmation that will never come.

**Proposed wording:** a write-only object is a *variable-length* object
advertising length 0, or an *event-class* object advertising its "none" value.
Nothing is lost — write-only exists for displays, buzzers and triggers, which
are exactly those classes. Implemented this way on both sides; the spec text is
what needs agreeing.

> **FR — Objets en écriture seule, cas des longueurs fixes : votre accord est
> nécessaire.**
>
> Réglé côté appareil : une entrée qui a un `set` et pas de `get` est en
> écriture seule, et le module la ré-advertise à longueur zéro (D-009).
>
> Reste ouvert pour les objets à **longueur fixe**, où « l'advertiser avec une
> valeur vide » n'a aucune représentation possible — un identifiant d'objet sans
> octet de valeur n'est pas quelque chose qu'un parseur BTHome sait parcourir.
> Une lampe éteinte advertise `1E 00`, octet pour octet identique à un
> emplacement vide. Un récepteur ne peut donc pas distinguer un déclencheur sans
> état d'un actionneur simplement éteint. Se tromper, c'est soit exposer un vrai
> interrupteur comme sans état, soit attendre indéfiniment une confirmation qui
> ne viendra jamais.
>
> **Formulation proposée :** un objet en écriture seule est un objet à
> *longueur variable* advertisé à longueur 0, ou un objet de *classe événement*
> advertisé à sa valeur « none ». Rien n'est perdu : l'écriture seule existe pour
> les afficheurs, les buzzers et les déclencheurs, qui sont exactement ces
> classes-là. Déjà implémenté ainsi des deux côtés ; c'est le texte de la spec
> qui attend votre accord.

---

## 4. `0x3B command` has no no-op — needs a decision

§4.3 says a write leaves an event object alone by sending its "none" value,
`0x00`. True for two of the three event objects:

| object | `0x00` means |
|---|---|
| `0x3A` button | none |
| `0x3C` dimmer | none |
| **`0x3B` command** | **`off`** |

`bthome-ble`'s `COMMAND_EVENTS` starts at `0x00: "off"` with no "none" anywhere.
Since a write carries *every* writable object (§4.2), a device declaring a
writable command alongside anything else cannot have that other thing written
without also commanding it — and today that command is `off`. A user toggling a
light would silently switch something off, and the protocol would call the write
correct.

Three ways out, none ours to pick: forbid declaring `0x3B` writable; give it a
no-op value outside the vocabulary; or let §4.3 admit some objects have no no-op
and require such an object to be a device's only writable one. Until then this
project offers no control for `0x3B` at all.

> **FR — `0x3B command` n'a pas de valeur neutre : une décision est requise.**
>
> Le §4.3 dit qu'une écriture laisse un objet événement tranquille en envoyant sa
> valeur « none », `0x00`. C'est vrai pour deux des trois objets événement, mais
> pas pour `0x3B command`, dont le `0x00` signifie **`off`** — une commande
> réelle. Le vocabulaire `COMMAND_EVENTS` de `bthome-ble` commence à
> `0x00: "off"` et ne contient aucun « none ».
>
> Or une écriture porte **tous** les objets writable (§4.2). Un appareil qui
> déclare une commande writable à côté d'autre chose ne peut donc pas voir cette
> autre chose écrite sans que la commande reçoive aussi quelque chose — et
> aujourd'hui ce quelque chose vaut `off`. Un utilisateur qui bascule une lampe
> éteindrait silencieusement autre chose, et le protocole considérerait
> l'écriture comme correcte.
>
> Trois issues, et ce n'est pas à nous de choisir : interdire de déclarer `0x3B`
> writable ; lui donner une valeur neutre hors vocabulaire ; ou admettre au §4.3
> que certains objets n'ont pas de valeur neutre et exiger qu'un tel objet soit
> le seul writable de l'appareil. En attendant, ce projet n'offre aucune commande
> pour `0x3B`.

---

## 5. §2.3's budget is wrong, and now has measurements

The working document said the usable budget was 23 bytes. Every radio measured
takes less, and two terms were never counted: Espruino's always-present `0x0590`
manufacturer data, and the local name.

| board / firmware | with name | without |
|---|---|---|
| Puck.js 2v27 | 17 | 20 |
| nice!nano 2v29.242 | 7 | 22 |

On the nice!nano the arithmetic that holds is 31 less 3 flags, 4 manufacturer
data, 4 service-data header, and `2 + len(name)` — and that firmware refuses
rather than shortening the name, so a thirteen-character default costs 15 bytes.
The Puck gives back only 3 when the name is dropped, so older builds evidently
do shorten it.

Eight writable one-byte objects plus the declaration come to 18, so the limit is
still workable — but "31" is misleading and the spec now says so. `showName:
false` is the first thing to try when a packet is refused. (D-030, D-046.)

> **FR — Le budget du §2.3 est faux, et il est désormais mesuré.**
>
> Le document de travail annonçait 23 octets utiles. Tous les radios mesurés en
> prennent moins, et deux termes n'avaient jamais été comptés : les données
> constructeur `0x0590` qu'Espruino ajoute systématiquement, et le nom local.
>
> Mesures : Puck.js 2v27 → 17 octets avec le nom, 20 sans. nice!nano 2v29.242 →
> 7 avec, 22 sans.
>
> Sur le nice!nano l'arithmétique qui tient est : 31 moins 3 de flags, 4 de
> données constructeur, 4 d'en-tête de service data, et `2 + longueur du nom`. Ce
> firmware refuse le paquet au lieu de raccourcir le nom, donc un nom par défaut
> de treize caractères coûte 15 octets. Le Puck ne rend que 3 octets quand on
> retire le nom : les builds plus anciens le raccourcissent manifestement.
>
> Huit objets writable d'un octet plus la déclaration font 18 octets, donc la
> limite reste vivable — mais « 31 » induit en erreur, et la spec le dit
> maintenant. `showName: false` est la première chose à essayer quand un paquet
> est refusé.

---

## 6. `AES.encrypt` in CTR mode ignores its `iv` — a security bug

Puck.js 2v27. Two IVs with no byte in common give the same answer, and it is
`E(0…0)`: the counter block is always zero.

```
iv 000102030405060708090a0b0c0d0e0f  ->  1838858c73da85d4885458a8e5dbda4f
iv ffeeddccbbaa99887766554433221100  ->  1838858c73da85d4885458a8e5dbda4f
AES-ECB of an all-zero block         =   1838858c73da85d4885458a8e5dbda4f
```

CBC and ECB are correct, byte for byte against a reference. `OFB` returns
`undefined`, possibly the same root cause.

Worth more than a bug report because it looks like it works: CTR over a nonce is
the obvious way to build a stream cipher, and this one uses one keystream for
every message under a key, so two ciphertexts XOR to the two plaintexts XORed.
Anyone who reached for it has no confidentiality between messages and nothing
told them. It costs us only an extra loop — we take the keystream from ECB
instead — so no hurry on our account. Reproduce with
`python -m tools.ccm_bench --address <mac>`.

> **FR — `AES.encrypt` en mode CTR ignore son `iv` : une faille de sécurité.**
>
> Sur Puck.js 2v27. Deux IV n'ayant aucun octet en commun donnent le même
> résultat, et ce résultat est `E(0…0)` : le bloc compteur est toujours nul. CBC
> et ECB sont corrects, octet pour octet contre une implémentation de référence.
> `OFB` renvoie `undefined`, peut-être la même cause racine.
>
> Cela vaut plus qu'un simple rapport de bug parce que **ça a l'air de
> fonctionner**. Le CTR sur un nonce est la façon évidente de construire un
> chiffrement par flot, et celui-ci utilise un seul flux de clé pour tous les
> messages sous une même clé : deux chiffrés XORés donnent les deux clairs
> XORés. Quiconque s'en est servi n'a aucune confidentialité entre messages, et
> rien ne le lui a dit.
>
> Pour nous le coût est seulement une boucle supplémentaire — nous prenons le
> flux de clé depuis ECB — donc rien ne presse de notre côté. Reproductible avec
> `python -m tools.ccm_bench --address <mac>`.

---

## 7. `AES.encrypt` returns `undefined` when it cannot allocate

It allocates its result as one contiguous run of heap. With no run that long it
prints `ERROR: Not enough memory for result` and returns `undefined`, so the
caller's `new Uint8Array(...)` throws `Unsupported first argument of type
undefined` at a line that has nothing wrong with it.

`process.memory().free` does not predict it — it counts free blocks, not
consecutive ones. In one session a 48-byte AES call failed while a REPL
`new Uint8Array(256)` succeeded. Throwing rather than returning `undefined`, and
saying *contiguous* rather than "not enough memory" with 24 kB free, would save
the next person the afternoon.

> **FR — `AES.encrypt` renvoie `undefined` quand il ne peut pas allouer.**
>
> Il alloue son résultat en une plage contiguë du tas. Quand aucune plage n'est
> assez longue, il affiche `ERROR: Not enough memory for result` et renvoie
> `undefined` — si bien que le `new Uint8Array(...)` de l'appelant lève
> `Unsupported first argument of type undefined`, en pointant une ligne qui n'a
> rien de fautif.
>
> `process.memory().free` ne le prédit pas : il compte les blocs libres, pas les
> blocs consécutifs. Dans une même session, un appel AES de 48 octets a échoué
> alors qu'un `new Uint8Array(256)` au REPL réussissait. Lever une exception
> plutôt que renvoyer `undefined`, et dire *contigu* plutôt que « pas assez de
> mémoire » avec 24 ko libres, épargnerait l'après-midi au suivant.

---

## 8. Settled, for the record

- **UUIDs.** One randomly assigned 128-bit base, second 16-bit group varying per
  characteristic: `2FAA0001-…` service, `2FAA0002-…` write. Adopted (D-001),
  frozen at first release.
- **Encrypted write field order** is `[ciphertext][counter u32 LE][MIC 4]`,
  matching BTHome's own encrypted advertising rather than the working document's
  original order (D-008).
- **The packet-id object shifts every bitmask bit.** Your worked example omitted
  it and got `FF 02`; a device using `getAdvertisement` emits it and gets
  `FF 04`. Now normative in §2.2 with the same device shown both ways.
- **`bthome-ble` tolerates the declaration**: unknown object IDs are skipped
  with a DEBUG log, no error — so it lives in the BTHome service data and the
  manufacturer-data fallback is not needed. Objects *after* the declaration are
  silently dropped, which is why "declaration last" is a MUST (D-005). It also
  already names duplicates `light_1`, `light_2`… by packet order, so its naming
  and our positional addressing agree by construction.
- **CCM is affordable and needs no JavaScript AES**: all vectors reproduce on a
  Puck.js 2v27 at 75 ms per frame, under 5 ms of it cipher. One ask remains —
  `USE_AES_CCM` is not set in the Puck.js build, and enabling it would remove
  our framing entirely.

> **FR — Réglé, pour mémoire.**
>
> - **UUID.** Une seule base 128 bits tirée au hasard, dont seul le deuxième
>   groupe de 16 bits varie par caractéristique : `2FAA0001-…` pour le service,
>   `2FAA0002-…` pour l'écriture. Adopté (D-001), figé à la première release.
> - **Ordre des champs d'une écriture chiffrée** :
>   `[chiffré][compteur u32 LE][MIC 4]`, ce qui reprend l'advertising chiffré de
>   BTHome plutôt que l'ordre initial du document de travail (D-008).
> - **L'objet packet id décale tous les bits du masque.** L'exemple de Gordon
>   l'omettait et donnait `FF 02` ; un appareil qui utilise `getAdvertisement`
>   l'émet et donne `FF 04`. C'est désormais normatif au §2.2, avec le même
>   appareil montré des deux façons.
> - **`bthome-ble` tolère la déclaration** : un identifiant d'objet inconnu est
>   sauté avec un log DEBUG, sans erreur — elle peut donc vivre dans le service
>   data BTHome, et le repli par données constructeur est inutile. Les objets
>   placés *après* la déclaration sont silencieusement perdus, ce qui est la
>   raison pour laquelle « déclaration en dernier » est un MUST (D-005). Cette
>   bibliothèque nomme déjà les doublons `light_1`, `light_2`… selon leur ordre
>   dans le paquet : son nommage et notre adressage positionnel coïncident donc
>   par construction.
> - **Le CCM est abordable et ne demande aucun AES en JavaScript** : tous les
>   vecteurs se reproduisent sur un Puck.js 2v27 à 75 ms par trame, dont moins de
>   5 ms de chiffrement. Une seule demande subsiste : `USE_AES_CCM` n'est pas
>   activé dans le build Puck.js, et l'activer supprimerait entièrement notre
>   couche d'assemblage.
