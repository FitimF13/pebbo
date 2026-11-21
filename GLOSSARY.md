# Pebbo

Pebbo is a self-hosted desk companion that talks, remembers and helps at home and in the office. This glossary is the shared language for the people who build it and the people who run their own.

## People

**Owner**:
The person who set up a Pebbo instance and runs it. Only the owner adds people, enables outside services and approves sensitive actions. Whoever builds their own Pebbo from this project becomes the owner of that instance.
_Avoid_: Admin, user, builder

**Maintainer**:
The person who runs the Pebbo project itself: reviews outside contributions and operates the project's shared services. Not the same as the owner of an instance.
_Avoid_: Admin, author, publisher

**Owner's agent**:
The coding agent an owner points at this project to choose hardware, set up their instance and adapt it to their needs. It is different from the agents that develop Pebbo itself.
_Avoid_: Installer, setup bot, assistant

**Person**:
Someone the owner added to an instance, with a role and permissions, whose voice Pebbo may learn after they agree.
_Avoid_: User, member, account, profile

**Role**:
The kind of person within an instance: adult, child or colleague. It sets which permissions a person starts with.
_Avoid_: Group, type

**Guest**:
Anyone Pebbo hears but does not recognise with enough confidence. A guest gets only general help, never personal data or device states.
_Avoid_: Unknown user, visitor, anonymous

**Household**:
The people of a home instance taken together, for example for shared routines and shared appointments.
_Avoid_: Family, home group

## Places and parts

**Instance**:
One Pebbo with its own people, memories, devices and data, such as the home Pebbo or the office Pebbo. Instances never read each other's data.
_Avoid_: Installation, deployment, tenant

**Core**:
The always-on part of an instance that holds its data and makes its decisions.
_Avoid_: Server, backend, hub

**Body**:
A device through which people see and talk to Pebbo, such as the desk robot or the PC app.
_Avoid_: Client, terminal, satellite

**Compute worker**:
Optional extra hardware or an external provider that an instance uses for heavier thinking or speech.
_Avoid_: Node, GPU server

**Relay**:
The optional outside helper that lets phones reach a home instance away from home, without seeing household data.
_Avoid_: Cloud, proxy, tunnel

## Behaviour

**Handoff**:
Information that a person prepared in one instance and the owner approved for another, such as the end-of-day summary from office to home. The only thing that travels between instances.
_Avoid_: Sync, transfer, export

**Routine**:
A behaviour a person taught Pebbo in plain language, which Pebbo confirms, saves and then runs on its own.
_Avoid_: Automation, rule, script
