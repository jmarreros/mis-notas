<?php

namespace Tests\Feature;

use App\Models\User;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Str;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

class SyncTest extends TestCase
{
    use RefreshDatabase;

    private function note(array $over = []): array
    {
        return array_merge([
            'id' => (string) Str::uuid(),
            'notebook_id' => null,
            'title' => 'Itinerario Kioto',
            'blocks' => [
                ['id' => 'b0', 'type' => 'p', 'html' => 'Reservar el <b>ryokan</b>'],
                ['id' => 'b1', 'type' => 'todo', 'items' => [['t' => 'JR Pass', 'done' => true]]],
            ],
            'tags' => ['Japón', '#pendiente', 'japón'],
            'created_at' => 1000,
            'updated_at' => 2000,
            'trashed_at' => null,
            'deleted_at' => null,
        ], $over);
    }

    private function push(array $notes = [], array $notebooks = [])
    {
        return $this->postJson('/api/sync', ['notebooks' => $notebooks, 'notes' => $notes]);
    }

    public function test_requires_token(): void
    {
        $this->getJson('/api/sync')->assertUnauthorized();
        $this->push()->assertUnauthorized();
    }

    public function test_push_then_pull_roundtrip(): void
    {
        Sanctum::actingAs(User::factory()->create());
        $nb = ['id' => (string) Str::uuid(), 'name' => 'Viajes', 'sort' => 0, 'created_at' => 1, 'updated_at' => 1];
        $note = $this->note(['notebook_id' => $nb['id']]);

        $this->push([$note], [$nb])->assertOk()->assertJson(['rev' => 2, 'notes' => [], 'notebooks' => []]);

        $res = $this->getJson('/api/sync?since=0')->assertOk();
        $res->assertJsonPath('rev', 2)
            ->assertJsonPath('notebooks.0.name', 'Viajes')
            ->assertJsonPath('notes.0.blocks.0.html', 'Reservar el <b>ryokan</b>')
            ->assertJsonPath('notes.0.blocks.1.items.0.done', true)
            ->assertJsonMissingPath('notes.0.tags')
            ->assertJsonMissingPath('notes.0.user_id');

        $this->getJson('/api/sync?since=2')->assertJson(['rev' => 2, 'notes' => [], 'notebooks' => []]);
    }

    public function test_last_write_wins(): void
    {
        Sanctum::actingAs(User::factory()->create());
        $note = $this->note(['updated_at' => 5000, 'title' => 'Nueva']);
        $this->push([$note])->assertOk();

        // Una versión más vieja se rechaza y el servidor devuelve la suya.
        $this->push([[...$note, 'title' => 'Vieja', 'updated_at' => 4000]])
            ->assertOk()
            ->assertJsonPath('rev', 1)
            ->assertJsonPath('notes.0.title', 'Nueva');

        // Una más nueva gana.
        $this->push([[...$note, 'title' => 'Más nueva', 'updated_at' => 6000]])
            ->assertJsonPath('rev', 2)->assertJsonPath('notes', []);
        $this->getJson('/api/sync?since=1')->assertJsonPath('notes.0.title', 'Más nueva');
    }

    public function test_tombstones_are_synced_and_final(): void
    {
        Sanctum::actingAs(User::factory()->create());
        $note = $this->note();
        $this->push([$note]);
        $this->push([[...$note, 'deleted_at' => 3000, 'updated_at' => 3000]]);

        $this->getJson('/api/sync?since=1')->assertJsonPath('notes.0.deleted_at', 3000);

        // Otro dispositivo con una edición posterior no la resucita.
        $this->push([[...$note, 'updated_at' => 9000]])->assertJsonPath('notes.0.deleted_at', 3000);
    }

    public function test_users_are_isolated(): void
    {
        $note = $this->note();
        Sanctum::actingAs(User::factory()->create());
        $this->push([$note])->assertOk();

        Sanctum::actingAs(User::factory()->create());
        $this->getJson('/api/sync?since=0')->assertJson(['rev' => 0, 'notes' => []]);
        $this->push([[...$note, 'updated_at' => 9999]])->assertStatus(409);
    }

    public function test_validation(): void
    {
        Sanctum::actingAs(User::factory()->create());
        $this->push([$this->note(['id' => 'no-uuid'])])->assertUnprocessable();
        $this->push([$this->note(['blocks' => [['type' => 'video']]])])->assertUnprocessable();
        $this->postJson('/api/sync', [])->assertUnprocessable();
    }
}
