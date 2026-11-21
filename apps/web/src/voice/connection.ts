import { clientReadyMessage, parseMessage, type PebboEvent } from './rtvi';

export interface ConnectionHandlers {
  onEvent(event: PebboEvent): void;
  onAudio(stream: MediaStream): void;
  onClosed(): void;
}

/**
 * A direct WebRTC connection between the browser and the Pebbo core on the local network.
 * No ICE servers are configured, so nothing is sent to public STUN or TURN servers.
 */
export class PebboConnection {
  private peer: RTCPeerConnection | undefined;
  private microphone: MediaStream | undefined;

  constructor(
    private readonly handlers: ConnectionHandlers,
    private readonly offerUrl = '/api/offer',
  ) {}

  async connect(): Promise<void> {
    this.microphone = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    const peer = new RTCPeerConnection({ iceServers: [] });
    this.peer = peer;
    for (const track of this.microphone.getAudioTracks()) peer.addTrack(track, this.microphone);

    const channel = peer.createDataChannel('pipecat');
    channel.onopen = () => channel.send(clientReadyMessage());
    channel.onmessage = (message: MessageEvent<string>) => {
      const event = parseMessage(message.data);
      if (event) this.handlers.onEvent(event);
    };
    peer.ontrack = (event) => {
      const [stream] = event.streams;
      this.handlers.onAudio(stream ?? new MediaStream([event.track]));
    };
    peer.onconnectionstatechange = () => {
      if (['failed', 'closed', 'disconnected'].includes(peer.connectionState)) this.handlers.onClosed();
    };

    await peer.setLocalDescription(await peer.createOffer());
    await iceGatheringComplete(peer);
    const response = await fetch(this.offerUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sdp: peer.localDescription?.sdp, type: 'offer' }),
    });
    if (!response.ok) throw new Error(`Pebbo did not accept the connection (${response.status}).`);
    const answer = (await response.json()) as RTCSessionDescriptionInit;
    await peer.setRemoteDescription(answer);
  }

  setMuted(muted: boolean): void {
    for (const track of this.microphone?.getAudioTracks() ?? []) track.enabled = !muted;
  }

  disconnect(): void {
    for (const track of this.microphone?.getTracks() ?? []) track.stop();
    this.peer?.close();
    this.peer = undefined;
    this.microphone = undefined;
  }
}

function iceGatheringComplete(peer: RTCPeerConnection): Promise<void> {
  if (peer.iceGatheringState === 'complete') return Promise.resolve();
  return new Promise((resolve) => {
    const timeout = window.setTimeout(resolve, 2000);
    peer.addEventListener('icegatheringstatechange', () => {
      if (peer.iceGatheringState === 'complete') {
        window.clearTimeout(timeout);
        resolve();
      }
    });
  });
}
